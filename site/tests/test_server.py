"""端到端测试 site/server.py:用假 LLMClient 驱动真实的 build_workflow(),
验证 HTTP 层真正打通了 engine.primitives.checkpoint.Checkpoint 的同步阻塞式
人工审核——这是本模块相对旧原型(subprocess + 轮询日志)最大的行为差异,
必须有一条测试覆盖到"浏览器 POST /checkpoint 之前,后台线程确实卡在等待"。

不直接 `import site.server`——`site` 是标准库模块名,用
importlib.util.spec_from_file_location 按路径加载,避免任何 sys.path 顺序
导致的名字遮蔽风险(见 site/server.py 模块 docstring)。同样的原因,运行本文件
不能用 `python3 -m unittest discover -s site/tests -t .`(顶层目录会把本文件
的 dotted module name 算成 "site.tests.test_server",一样撞上标准库 site);
要用:

    python3 -m unittest discover -s site/tests -t site/tests

这个场景包本身也是"独立、后续可能被移出本仓库"的一部分(见 scenarios/
development-guide.md),所以它的测试不放进框架的 tests/ 目录,自成一套。
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _load_server_module():
    spec = importlib.util.spec_from_file_location("essay_httpserver", REPO_ROOT / "site" / "server.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # dataclasses(见 site/server.py 的 RunState)需要能在 sys.modules 里找到
    # 自己的模块对象来解析带 `from __future__ import annotations` 的类型注解,
    # 必须在 exec_module 之前就注册,否则会在 @dataclass 装饰阶段直接炸掉。
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


server = _load_server_module()

from llm.client import ChatResponse, LLMClient  # noqa: E402
from llm.image_client import ImageClient, ImageResult  # noqa: E402
from llm.message import Message  # noqa: E402
from scenarios.essay.brief import parse_brief  # noqa: E402
from scenarios.essay.schemas.state import BRIEF_PATH, DRAFT_PATH, META_PATH, PLAN_PATH, REVIEW_PATH, COVER_BRIEF_PATH, empty_state  # noqa: E402
from scenarios.essay.workflow import build_workflow  # noqa: E402
from scenarios.essay import landing  # noqa: E402
from state.backends.json_file import JsonFileStateStore  # noqa: E402
from engine.context import RunContext  # noqa: E402

PLAN_VALUE = {
    "protagonist_name": "卫知遥",
    "audience": "青年",
    "hook": "开篇冲突",
    "synopsis": "摘要",
    "chapters": [{"index": 1, "summary": "s", "target_word_count": 10, "is_climax": True}],
}
# brief 走真实的 parse_brief 校验(min_words 下限锁死 6000),正文长度必须
# 落在 [6000, 20000] 区间内,否则 merge_rejection 会因为字数不达标一直打回。
DRAFT_VALUE = [{"index": 1, "title": "第一章", "content": "文" * 6500, "word_count": 0}]
META_VALUE = {
    "title": "重生后我惊艳全家",
    "blurb": "一段推广简介",
    "tags": {
        "category": ["婚姻家庭"],
        "plot": ["打脸逆袭"],
        "character": ["霸总"],
        "emotion": ["爽文"],
        "setting": ["豪门世家"],
    },
    "preview_ratio": 0.18,
}


class _ScriptedClient(LLMClient):
    def __init__(self, script: list[dict]) -> None:
        self._script = list(script)

    def chat(self, messages, tools=None, response_schema=None, **params) -> ChatResponse:
        payload = self._script.pop(0) if len(self._script) > 1 else self._script[0]
        return ChatResponse(message=Message(role="assistant", content=json.dumps(payload, ensure_ascii=False)))


class _FakeImageClient(ImageClient):
    def generate(self, prompt: str, **params) -> ImageResult:
        return ImageResult(url="https://example.com/cover.png")


def _make_fake_run_workflow(planning_calls: int = 1):
    """构造一个 server.run_workflow 的替身:接口与真版一致,内部换成
    build_workflow() + 假 LLMClient/ImageClient,不需要真实 API Key/网络。

    测试的目标是 site/server.py 自己的桥接逻辑(线程、事件队列、Checkpoint
    阻塞/唤醒),真实的 reads/writes/游标编排已经在
    scenarios/essay/tests/test_workflow.py 里覆盖过,这里不重复断言。
    """

    def fake_run_workflow(
        brief,
        *,
        output_dir,
        state_path,
        default_credentials=None,
        stage_credentials=None,
        image_client=None,
        checkpoint_handler=None,
        hooks=None,
        log_dir=None,
        fresh=True,
    ):
        brief = parse_brief(brief)
        planning_client = _ScriptedClient([{PLAN_PATH: PLAN_VALUE}] * planning_calls)
        drafting_client = _ScriptedClient([{DRAFT_PATH: DRAFT_VALUE}])
        review_client = _ScriptedClient(
            [{DRAFT_PATH: DRAFT_VALUE, REVIEW_PATH: {"rejected": False, "feedback": ""}}]
        )
        meta_client = _ScriptedClient([{META_PATH: META_VALUE}])
        cover_client = _ScriptedClient([{COVER_BRIEF_PATH: "视觉描述"}])
        clients = {
            "planning": planning_client,
            "drafting": drafting_client,
            "review": review_client,
            "meta": meta_client,
            "cover": cover_client,
        }
        workflow = build_workflow(
            client_factory=lambda stage_name, model=None: clients[stage_name],
            image_client=_FakeImageClient(),
            human_review=brief["human_review"],
            generate_cover=brief["generate_cover"],
        )

        # 用真的 JsonFileStateStore(不是 InMemoryStateStore):/api/runs/{id}/state
        # 这条路由直接读磁盘上的 state_path,测试要能验真的落盘了才有意义。
        store = JsonFileStateStore(state_path)
        store.load(empty_state())
        store.patch(BRIEF_PATH, brief)
        ctx = RunContext(state=store, checkpoint_handler=checkpoint_handler, hooks=hooks)

        from engine.workflow import WorkflowFailure
        from engine.primitives.loop import LoopExceededError
        from scenarios.essay.nodes.planning import PLANNING_CHECKPOINT_LOOP_NAME
        from scenarios.essay.run import PlanningRejectedError

        try:
            workflow.run(ctx, {})
        except WorkflowFailure as failure:
            if isinstance(failure.__cause__, LoopExceededError) and PLANNING_CHECKPOINT_LOOP_NAME in str(
                failure.__cause__
            ):
                raise PlanningRejectedError("情节规划连续被驳回超过允许次数,任务已终止。") from failure
            raise

        return landing.write(store.snapshot(), output_dir)

    return fake_run_workflow


class ServerTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_run_workflow = server.run_workflow
        self.addCleanup(lambda: setattr(server, "run_workflow", self._orig_run_workflow))

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.port = self.httpd.server_address[1]
        self.thread = Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.httpd.shutdown)
        self.addCleanup(self.httpd.server_close)

        self.addCleanup(lambda: shutil.rmtree(server.RUNS_DIR, ignore_errors=True))

    def _url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def _post(self, path: str, payload: dict) -> tuple[int, dict]:
        req = urllib.request.Request(
            self._url(path),
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as err:
            return err.code, json.loads(err.read())

    def _get(self, path: str) -> tuple[int, dict]:
        try:
            with urllib.request.urlopen(self._url(path), timeout=5) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as err:
            return err.code, json.loads(err.read())

    def _get_raw(self, path: str) -> tuple[int, bytes, dict]:
        try:
            with urllib.request.urlopen(self._url(path), timeout=5) as resp:
                return resp.status, resp.read(), dict(resp.headers)
        except urllib.error.HTTPError as err:
            return err.code, err.read(), dict(err.headers)

    def _wait_for_status(self, run_id: str, targets: set[str], timeout: float = 5.0) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            status, payload = self._get(f"/api/runs/{run_id}/status")
            self.assertEqual(status, 200)
            if payload["status"] in targets:
                return payload
            time.sleep(0.02)
        self.fail(f"超时:run 状态没有到达 {targets},最后一次是 {payload}")

    def _brief(self, **overrides) -> dict:
        # min_words/max_words 留给 parse_brief 的默认值(6000/20000),与
        # DRAFT_VALUE 的长度对应,避免字数判定意外打回。generate_cover 默认
        # 关闭(见 brief.py),这里显式打开以覆盖封面这条路径。
        base = {"synopsis": "一个测试用简介", "human_review": False, "generate_cover": True}
        base.update(overrides)
        return base

    def _credentials(self) -> dict:
        return {"default": {"model": "fake-model", "base_url": "http://fake.local", "api_key": "fake-key"}}


class CheckpointBridgeTests(ServerTestCase):
    def test_checkpoint_blocks_until_http_answers_then_run_completes(self) -> None:
        server.run_workflow = _make_fake_run_workflow(planning_calls=1)

        status, data = self._post(
            "/api/runs",
            {"brief": self._brief(human_review=True), **self._credentials()},
        )
        self.assertEqual(status, 200)
        run_id = data["run_id"]

        payload = self._wait_for_status(run_id, {"awaiting_checkpoint"})
        self.assertEqual(payload["checkpoint"]["name"], "confirm_planning")

        # 还没回答之前,run 应该稳定卡在 awaiting_checkpoint(不会自己跑完)。
        time.sleep(0.1)
        still_waiting = self._get(f"/api/runs/{run_id}/status")[1]
        self.assertEqual(still_waiting["status"], "awaiting_checkpoint")

        status, _ = self._post(f"/api/runs/{run_id}/checkpoint", {"approved": True, "feedback": ""})
        self.assertEqual(status, 200)

        self._wait_for_status(run_id, {"success", "failed", "terminated_rejected"})

        status, result = self._get(f"/api/runs/{run_id}/result")
        self.assertEqual(status, 200)
        self.assertEqual(result["plan"]["protagonist_name"], "卫知遥")
        self.assertEqual(result["cover_image"]["url"], "https://example.com/cover.png")
        self.assertFalse(result["needs_manual_review"])
        self.assertEqual(result["meta"]["title"], META_VALUE["title"])
        self.assertEqual(result["meta"]["tags"]["plot"], ["打脸逆袭"])

    def test_events_stream_reports_stage_progress(self) -> None:
        server.run_workflow = _make_fake_run_workflow(planning_calls=1)

        _, data = self._post("/api/runs", {"brief": self._brief(human_review=False), **self._credentials()})
        run_id = data["run_id"]
        self._wait_for_status(run_id, {"success", "failed", "terminated_rejected"})

        with urllib.request.urlopen(self._url(f"/api/runs/{run_id}/events"), timeout=5) as resp:
            self.assertIn("text/event-stream", resp.headers.get("Content-Type", ""))
            body = resp.read().decode("utf-8")

        self.assertIn('"event": "stage_start"', body)
        self.assertIn('"event": "done"', body)
        # 审核发现的问题(通过/打回+具体原因)要打进事件流,不能只有一句空壳的
        # "[完成] review",不然用户在页面上看不出为什么会有改稿循环。
        self.assertIn('"event": "review_result"', body)
        self.assertIn('"rejected": false', body)

    def test_review_result_event_reports_rejection_feedback(self) -> None:
        # min_words 定得比 DRAFT_VALUE(6500 字)高,让首轮审核因为字数不达标
        # 被系统判定打回,验证 review_result 事件真的带上了具体的驳回原因。
        server.run_workflow = _make_fake_run_workflow(planning_calls=1)

        _, data = self._post(
            "/api/runs",
            {"brief": self._brief(human_review=False, min_words=7000, max_words=20000), **self._credentials()},
        )
        run_id = data["run_id"]
        self._wait_for_status(run_id, {"success", "failed", "terminated_rejected"})

        with urllib.request.urlopen(self._url(f"/api/runs/{run_id}/events"), timeout=5) as resp:
            body = resp.read().decode("utf-8")

        self.assertIn('"event": "review_result"', body)
        self.assertIn('"rejected": true', body)
        self.assertIn("低于下限", body)


class PlanningRejectedTests(ServerTestCase):
    def test_three_rejections_terminate_with_red_flag_status(self) -> None:
        server.run_workflow = _make_fake_run_workflow(planning_calls=3)

        _, data = self._post("/api/runs", {"brief": self._brief(human_review=True), **self._credentials()})
        run_id = data["run_id"]

        for _ in range(3):
            self._wait_for_status(run_id, {"awaiting_checkpoint"})
            self._post(f"/api/runs/{run_id}/checkpoint", {"approved": False, "feedback": "再改改"})

        payload = self._wait_for_status(run_id, {"terminated_rejected", "success", "failed"})
        self.assertEqual(payload["status"], "terminated_rejected")

        status, result = self._get(f"/api/runs/{run_id}/result")
        self.assertEqual(status, 200)
        self.assertEqual(result["status"], "terminated_rejected")


class TaskListAndPhaseTests(ServerTestCase):
    """GET /api/runs(任务栏列表)与 /status 里新增的 title/brief/phase_order/
    phases 字段——驱动前端任务栏轮盘的球体高亮与阶段小圆点。"""

    def test_runs_list_reports_active_phase_during_checkpoint_wait(self) -> None:
        server.run_workflow = _make_fake_run_workflow(planning_calls=1)

        _, data = self._post("/api/runs", {"brief": self._brief(human_review=True), **self._credentials()})
        run_id = data["run_id"]
        self._wait_for_status(run_id, {"awaiting_checkpoint"})

        status, payload = self._get("/api/runs")
        self.assertEqual(status, 200)
        entries = {r["run_id"]: r for r in payload["runs"]}
        self.assertIn(run_id, entries)
        entry = entries[run_id]
        self.assertEqual(entry["status"], "awaiting_checkpoint")
        self.assertEqual(entry["phase_order"], ["planning", "drafting", "review", "meta", "cover"])
        # planning 的 Stage 本身已经跑完,但 Checkpoint 还没通过——阶段小圆点
        # 停在 active,不能提前标 done(万一被驳回还要再跑一轮 planning)。
        self.assertEqual(entry["phases"]["planning"], "active")
        self.assertEqual(entry["phases"]["drafting"], "pending")

        self._post(f"/api/runs/{run_id}/checkpoint", {"approved": True, "feedback": ""})
        self._wait_for_status(run_id, {"success", "failed", "terminated_rejected"})

    def test_all_phases_done_after_success(self) -> None:
        server.run_workflow = _make_fake_run_workflow(planning_calls=1)

        _, data = self._post("/api/runs", {"brief": self._brief(human_review=False), **self._credentials()})
        run_id = data["run_id"]
        self._wait_for_status(run_id, {"success", "failed", "terminated_rejected"})

        status, payload = self._get("/api/runs")
        entry = next(r for r in payload["runs"] if r["run_id"] == run_id)
        self.assertEqual(entry["status"], "success")
        self.assertTrue(all(v == "done" for v in entry["phases"].values()), entry["phases"])

    def test_generate_cover_false_excludes_cover_phase(self) -> None:
        server.run_workflow = _make_fake_run_workflow(planning_calls=1)

        _, data = self._post(
            "/api/runs",
            {"brief": self._brief(human_review=False, generate_cover=False), **self._credentials()},
        )
        run_id = data["run_id"]
        self._wait_for_status(run_id, {"success", "failed", "terminated_rejected"})

        status, payload = self._get(f"/api/runs/{run_id}/status")
        self.assertEqual(status, 200)
        self.assertNotIn("cover", payload["phase_order"])
        self.assertNotIn("cover", payload["phases"])

    def test_status_endpoint_exposes_brief_and_meta_title(self) -> None:
        server.run_workflow = _make_fake_run_workflow(planning_calls=1)

        _, data = self._post("/api/runs", {"brief": self._brief(human_review=False), **self._credentials()})
        run_id = data["run_id"]
        self._wait_for_status(run_id, {"success", "failed", "terminated_rejected"})

        status, payload = self._get(f"/api/runs/{run_id}/status")
        self.assertEqual(status, 200)
        self.assertEqual(payload["brief"]["synopsis"], self._brief()["synopsis"])
        # meta 节点跑完之后,任务标题应该被替换成 meta.title,不再是创建时用
        # 简介顶的占位标题。
        self.assertEqual(payload["title"], META_VALUE["title"])


class DiskReconstructionTests(ServerTestCase):
    """服务器重启后,site/server.py 启动时会调用 _load_runs_from_disk() 重新
    扫描 RUNS_DIR、把历史任务挂回 RUNS,这里直接调用这个函数验证(不需要真的
    重启进程/重新 import 一次模块)。"""

    def _parsed_brief(self, **overrides) -> dict:
        base = {
            "synopsis": "一个测试用简介",
            "min_words": 6000,
            "max_words": 20000,
            "category": "",
            "audience": "",
            "human_review": False,
            "cover_prompt": "",
            "generate_cover": True,
        }
        base.update(overrides)
        return base

    def _write_state_file(self, run_dir: Path, essay_state: dict) -> None:
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / server.STATE_FILENAME).write_text(
            json.dumps({"essay_state": essay_state}, ensure_ascii=False), encoding="utf-8"
        )

    def test_rebuilds_successful_run_from_story_json(self) -> None:
        run_id = "20200101_000000_aaaaaa"  # 固定的过去时间戳,不会和其它测试真正生成的 run_id 撞
        run_dir = server.RUNS_DIR / run_id
        self.addCleanup(lambda: server.RUNS.pop(run_id, None))

        self._write_state_file(
            run_dir,
            {
                "brief": self._parsed_brief(),
                "plan": PLAN_VALUE,
                "draft": DRAFT_VALUE,
                "review": {"rejected": False, "feedback": ""},
                "meta": META_VALUE,
                "cover_brief": "视觉描述",
                "cover_image": {"url": "https://example.com/cover.png", "note": ""},
            },
        )
        story = {
            "plan": PLAN_VALUE,
            "chapters": DRAFT_VALUE,
            "total_words": 6500,
            "review": {"rejected": False, "feedback": ""},
            "needs_manual_review": False,
            "meta": META_VALUE,
            "cover_brief": "视觉描述",
            "cover_image": {"url": "https://example.com/cover.png", "note": ""},
            "manuscript_path": str(run_dir / "output" / "manuscript.md"),
            "story_path": str(run_dir / "output" / "story.json"),
        }
        (run_dir / "output").mkdir(parents=True, exist_ok=True)
        (run_dir / "output" / "manuscript.md").write_text("# 正文\n", encoding="utf-8")
        (run_dir / "output" / "story.json").write_text(json.dumps(story, ensure_ascii=False), encoding="utf-8")

        server._load_runs_from_disk()

        status, payload = self._get("/api/runs")
        self.assertEqual(status, 200)
        entries = {r["run_id"]: r for r in payload["runs"]}
        self.assertIn(run_id, entries)
        self.assertEqual(entries[run_id]["status"], "success")
        self.assertEqual(entries[run_id]["title"], META_VALUE["title"])
        self.assertTrue(all(v == "done" for v in entries[run_id]["phases"].values()), entries[run_id]["phases"])

        status, result = self._get(f"/api/runs/{run_id}/result")
        self.assertEqual(status, 200)
        self.assertEqual(result["meta"]["title"], META_VALUE["title"])

        # 重建出来的 success run 也能正常下载正文——manuscript_path 指向的
        # 文件是重建之前(“上一辈子”)就已经落在磁盘上的,不需要重新生成。
        status, body, headers = self._get_raw(f"/api/runs/{run_id}/download")
        self.assertEqual(status, 200)
        self.assertIn("正文", body.decode("utf-8"))

    def test_rebuilds_interrupted_run_without_story_json(self) -> None:
        run_id = "20200101_000000_bbbbbb"
        run_dir = server.RUNS_DIR / run_id
        self.addCleanup(lambda: server.RUNS.pop(run_id, None))

        empty_tags = {"category": [], "plot": [], "character": [], "emotion": [], "setting": []}
        self._write_state_file(
            run_dir,
            {
                "brief": self._parsed_brief(),
                "plan": PLAN_VALUE,  # planning 阶段跑完了
                "draft": [],  # 但还没写出正文——卡在 drafting 之前/中途
                "review": {"rejected": False, "feedback": ""},
                "meta": {"title": "", "blurb": "", "tags": empty_tags},
                "cover_brief": "",
                "cover_image": {"url": "", "note": ""},
            },
        )
        # 故意不写 output/story.json:模拟"进程在跑完之前就被杀掉了"。

        server._load_runs_from_disk()

        status, payload = self._get("/api/runs")
        self.assertEqual(status, 200)
        entries = {r["run_id"]: r for r in payload["runs"]}
        self.assertIn(run_id, entries)
        self.assertEqual(entries[run_id]["status"], "interrupted")
        self.assertEqual(entries[run_id]["phases"]["planning"], "done")
        self.assertEqual(entries[run_id]["phases"]["drafting"], "pending")

        status, result = self._get(f"/api/runs/{run_id}/result")
        self.assertEqual(status, 200)
        self.assertEqual(result["status"], "interrupted")
        self.assertIn("重启", result["error"])

    def test_ignores_run_directory_without_state_file(self) -> None:
        run_id = "20200101_000000_cccccc"
        run_dir = server.RUNS_DIR / run_id
        run_dir.mkdir(parents=True, exist_ok=True)  # 空目录,essay_state.json 都没有

        server._load_runs_from_disk()

        self.assertNotIn(run_id, server.RUNS)


class DownloadRoutesTests(ServerTestCase):
    """/download 和 /state 是"抓产物排查问题"用的路由:前者拿排版好的正文,
    后者拿原始状态快照(不按 run.status 门控,卡住/失败的 run 也要能拿到)。"""

    def test_download_returns_manuscript_after_success(self) -> None:
        server.run_workflow = _make_fake_run_workflow(planning_calls=1)

        _, data = self._post("/api/runs", {"brief": self._brief(human_review=False), **self._credentials()})
        run_id = data["run_id"]
        self._wait_for_status(run_id, {"success", "failed", "terminated_rejected"})

        status, body, headers = self._get_raw(f"/api/runs/{run_id}/download")
        self.assertEqual(status, 200)
        self.assertIn(f'filename="{run_id}.md"', headers.get("Content-Disposition", ""))
        self.assertIn("第一章", body.decode("utf-8"))

    def test_state_returns_raw_snapshot_while_running(self) -> None:
        server.run_workflow = _make_fake_run_workflow(planning_calls=1)

        _, data = self._post(
            "/api/runs", {"brief": self._brief(human_review=True), **self._credentials()}
        )
        run_id = data["run_id"]
        # 特意在 awaiting_checkpoint(还没跑完)时就抓状态快照:这正是
        # "运行卡住/失败,需要在结束前就能看到当前状态"的场景。
        self._wait_for_status(run_id, {"awaiting_checkpoint"})

        status, body, headers = self._get_raw(f"/api/runs/{run_id}/state")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Content-Type"), "application/json; charset=utf-8")
        snapshot = json.loads(body)
        self.assertEqual(
            snapshot["essay_state"]["brief"]["synopsis"], self._brief(human_review=True)["synopsis"]
        )

        self._post(f"/api/runs/{run_id}/checkpoint", {"approved": True, "feedback": ""})
        self._wait_for_status(run_id, {"success", "failed", "terminated_rejected"})

    def test_state_404_for_unknown_run(self) -> None:
        status, _, _ = self._get_raw("/api/runs/does-not-exist/state")
        self.assertEqual(status, 404)


class MonthlyTrendsRouteTests(ServerTestCase):
    """GET /api/monthly-trends 直接把 trend.load_monthly_trend_options() 的
    结果原样透出,供前端"月度热点"页签渲染可选方向列表。"""

    def test_returns_parsed_options(self) -> None:
        orig = server.load_monthly_trend_options
        server.load_monthly_trend_options = lambda: [{"title": "t1", "description": "d1"}]
        self.addCleanup(lambda: setattr(server, "load_monthly_trend_options", orig))

        status, data = self._get("/api/monthly-trends")
        self.assertEqual(status, 200)
        self.assertEqual(data["options"], [{"title": "t1", "description": "d1"}])

    def test_returns_empty_list_when_no_trend_file(self) -> None:
        orig = server.load_monthly_trend_options
        server.load_monthly_trend_options = lambda: []
        self.addCleanup(lambda: setattr(server, "load_monthly_trend_options", orig))

        status, data = self._get("/api/monthly-trends")
        self.assertEqual(status, 200)
        self.assertEqual(data["options"], [])


class CreateRunValidationTests(ServerTestCase):
    def test_invalid_brief_is_rejected_synchronously(self) -> None:
        status, data = self._post("/api/runs", {"brief": {"synopsis": ""}})
        self.assertEqual(status, 400)
        self.assertIn("synopsis", data["error"])

    def test_missing_default_credentials_is_rejected(self) -> None:
        status, data = self._post("/api/runs", {"brief": self._brief()})
        self.assertEqual(status, 400)
        self.assertIn("default", data["error"])

    def test_partial_default_credentials_is_rejected(self) -> None:
        status, data = self._post(
            "/api/runs",
            {"brief": self._brief(), "default": {"model": "fake-model"}},  # 缺 base_url/api_key
        )
        self.assertEqual(status, 400)
        self.assertIn("default", data["error"])

    def test_unknown_stage_name_is_rejected(self) -> None:
        status, data = self._post(
            "/api/runs",
            {"brief": self._brief(), **self._credentials(), "stages": {"typo_stage": {"model": "x"}}},
        )
        self.assertEqual(status, 400)
        self.assertIn("typo_stage", data["error"])


if __name__ == "__main__":
    unittest.main()
