"""essay 场景的 Web 化生产界面 —— 后端入口。

不引入 Flask/FastAPI 等新依赖(仓库里没装任何 web 框架,requirements.txt 只有
三个 LLM SDK),用标准库 `http.server.ThreadingHTTPServer` 自己写路由分发。

和"跑一条 CLI 命令再解析日志"的做法不同:这里让每个 run 在**进程内的后台
线程**里跑 `scenarios.essay.run.run_workflow(...)`,因为情节规划的人工审核用
了 `engine.primitives.checkpoint.Checkpoint`——`ctx.checkpoint_handler` 是一次
同步阻塞调用,必须真的把某个线程挂起等浏览器答复,subprocess+轮询日志的方式
做不到这一点。`checkpoint_handler` 用 `threading.Event` 阻塞,`POST
.../checkpoint` 把答案塞进去再唤醒。

多个 run 各自一个线程 + 各自独立的状态文件,互不阻塞,可以并发跑。

启动(注意:是直接跑脚本,不要用 `python -m site.server`——`site` 是标准库
模块名,`-m` 方式的模块解析会被标准库的 `site` 抢先命中):

    python site/server.py [--host 127.0.0.1] [--port 8000]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# 运行时才把仓库根目录挂到 sys.path,不依赖 PYTHONPATH——见模块 docstring
# 关于为什么不用 `python -m site.server` 启动。
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from engine.context import CheckpointRequest, LifecycleHooks  # noqa: E402
from llm.image_client import NotConfiguredImageClient  # noqa: E402
from scenarios.essay.brief import parse_brief  # noqa: E402
from scenarios.essay.run import (  # noqa: E402
    STAGE_NAMES,
    PlanningRejectedError,
    StageCredentials,
    run_workflow,
)
from scenarios.essay.schemas.state import REVIEW_PATH  # noqa: E402
from scenarios.essay.trend import load_monthly_trend_options  # noqa: E402

STATIC_DIR = Path(__file__).with_name("static")
RUNS_DIR = Path(__file__).with_name("runs")
STATE_FILENAME = "essay_state.json"

# 由 --log-chats 命令行开关控制,main() 里按需改写;开启后每个 run 的每次
# chat() 请求/响应(含 stop_reason)会落到 run_dir/log/chat_NNNN.json,供事后
# 排查"内容被截断"这类只看最终产物猜不出原因的问题(见 llm/logging_client.py)。
LOG_CHATS = False

# interrupted:进程重启前没跑完、又没法确认真的是异常失败(见
# _rebuild_run_from_disk)的历史任务专用状态,和 failed 区分开——不是代码
# 抛了异常,只是服务器重启把这个 run 的后台线程连同它的 checkpoint_ready
# Event 一起带走了,httpserver 不支持跨进程续跑,只能标成终态。
TERMINAL_STATUSES = {"success", "failed", "terminated_rejected", "interrupted"}

STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
}

_RUN_GET_RE = re.compile(r"^/api/runs/([^/]+)/(status|events|result|download|state)$")
_RUN_CHECKPOINT_RE = re.compile(r"^/api/runs/([^/]+)/checkpoint$")

# 前端任务栏用这份固定顺序渲染每个任务下面的阶段小圆点(见 index.html/app.js
# 的任务栏说明)。first_draft/redraft 都算"drafting"阶段、cover_brief/
# cover_image 都算"cover"阶段——阶段点是给用户看的粗粒度进度,不需要精确到
# Stage 级别;改稿循环可能让 drafting/review 反复触发,但阶段点只关心"这个
# 阶段有没有开始过/是否已经交棒给下一个阶段",不逐轮细分。
PHASE_STAGE_MAP = {
    "planning": "planning",
    "first_draft": "drafting",
    "redraft": "drafting",
    "review": "review",
    "meta": "meta",
    "cover_brief": "cover",
    "cover_image": "cover",
}


def _phase_order_for(brief: dict[str, Any]) -> list[str]:
    order = ["planning", "drafting", "review", "meta"]
    if brief.get("generate_cover"):
        order.append("cover")
    return order


def _title_from_synopsis(synopsis: str) -> str:
    # meta 节点跑完之前(甚至跑到一半就失败)都还没有正式标题,先用简介的
    # 开头顶一下,好歹能在任务栏里认出是哪个任务;跑成功之后 _run_thread 会
    # 用 meta.title 覆盖掉这个占位值。
    synopsis = (synopsis or "").strip()
    return synopsis if len(synopsis) <= 24 else synopsis[:24] + "…"


class HttpError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


# ---------------------------------------------------------------------------
# 运行态
# ---------------------------------------------------------------------------


@dataclass
class RunState:
    run_id: str
    run_dir: Path
    brief: dict[str, Any] = field(default_factory=dict)
    title: str = ""
    created_at: float = field(default_factory=time.time)
    # phase_order 是这次 run 实际会经过的阶段(取决于 brief.generate_cover),
    # phases 是每个阶段当前的进度:pending(还没开始) | active(进行中) |
    # done(已完成) | error(run 在这个阶段失败/终止时结束的)。任务栏的阶段
    # 小圆点直接按这两份数据渲染,见 _track_phase/_finalize_phases。
    phase_order: list[str] = field(default_factory=list)
    phases: dict[str, str] = field(default_factory=dict)
    status: str = "running"  # running | awaiting_checkpoint | success | failed | terminated_rejected | interrupted
    events: list[dict[str, Any]] = field(default_factory=list)
    pending_checkpoint: dict[str, Any] | None = None
    checkpoint_answer: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)
    new_event: threading.Event = field(default_factory=threading.Event)
    checkpoint_ready: threading.Event = field(default_factory=threading.Event)


RUNS: dict[str, RunState] = {}
RUNS_LOCK = threading.Lock()


def _created_at_from_run_id(run_id: str) -> float:
    """run_id 的前 15 个字符是创建时刻的 "%Y%m%d_%H%M%S"(见 _handle_create_run
    生成 run_id 的写法),从磁盘重建 RunState 时没有别的地方能拿到真实创建
    时间——状态文件的 mtime 是"最后一次落盘时间",进度越多的 run 反而越晚,
    会把任务栏的先后顺序搞乱,不能用。解析不出来时兜底成 0(排最前面)。
    """
    try:
        return time.mktime(time.strptime(run_id[:15], "%Y%m%d_%H%M%S"))
    except ValueError:
        return 0.0


def _rebuild_run_from_disk(run_dir: Path) -> RunState | None:
    """把一个 run 目录重新挂载成任务栏能看到的只读记录(不会真的续跑,见
    RunState.status 里 "interrupted" 的说明)。

    只依赖 essay_state.json(run_workflow 一开始 load(empty_state()) +
    patch(BRIEF_PATH, brief) 就已经落过盘,只要线程真正跑起来过就一定有)和
    output/story.json(landing.write() 产出,只有整个工作流跑完才会写)这两
    份东西,都是每个 run 目录里本来就会写的文件,不需要额外持久化任何状态。
    """
    state_path = run_dir / STATE_FILENAME
    if not state_path.is_file():
        return None  # 目录存在但状态文件都没有,创建请求大概率没真正跑起来
    try:
        snapshot = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    essay = snapshot.get("essay_state") or {}
    brief = essay.get("brief") or {}
    if not brief.get("synopsis"):
        return None

    run_id = run_dir.name
    phase_order = _phase_order_for(brief)
    created_at = _created_at_from_run_id(run_id)
    meta = essay.get("meta") or {}
    title = meta.get("title") or _title_from_synopsis(brief.get("synopsis", ""))

    story_path = run_dir / "output" / "story.json"
    if story_path.is_file():
        try:
            result = json.loads(story_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            result = None
        if result is not None:
            return RunState(
                run_id=run_id,
                run_dir=run_dir,
                brief=brief,
                title=(result.get("meta") or {}).get("title") or title,
                created_at=created_at,
                phase_order=phase_order,
                phases={phase: "done" for phase in phase_order},
                status="success",
                result=result,
            )

    # 没有 story.json:工作流没跑完服务器就重启了。阶段进度按状态快照里已经
    # 写了哪些字段做个粗略估计——不追求精确(比如没法区分"review 通过了"和
    # "review 从没跑过",干脆按"有没有正文"一并处理),反正这个 run 已经跑
    # 不动了,阶段点只是给用户一个大致印象,不是精确的进度条。
    draft = essay.get("draft") or []
    reached = {
        "planning": bool((essay.get("plan") or {}).get("protagonist_name")),
        "drafting": bool(draft),
        "review": bool(draft),
        "meta": bool(meta.get("title")),
        "cover": bool(essay.get("cover_brief")) or bool((essay.get("cover_image") or {}).get("url")),
    }
    phases = {phase: ("done" if reached.get(phase) else "pending") for phase in phase_order}

    return RunState(
        run_id=run_id,
        run_dir=run_dir,
        brief=brief,
        title=title,
        created_at=created_at,
        phase_order=phase_order,
        phases=phases,
        status="interrupted",
        error="服务器重启导致该任务被中断,无法继续;如需要请重新提交一次。",
    )


def _load_runs_from_disk() -> None:
    """启动时调用一次,把 RUNS_DIR 下遗留的 run 目录重新挂载进 RUNS,这样
    任务栏在服务器重启后依旧能看到历史任务(至少是已经成功产出的那些,
    还能下载/复制;没跑完的会标成 interrupted,不会假装还在跑)。"""
    if not RUNS_DIR.is_dir():
        return
    for run_dir in sorted(RUNS_DIR.iterdir()):
        if not run_dir.is_dir():
            continue
        run = _rebuild_run_from_disk(run_dir)
        if run is not None:
            RUNS[run.run_id] = run


def _credentials_from_body(raw: Any, *, field_name: str) -> StageCredentials:
    """把请求体里 {"model":..., "base_url":..., "api_key":...} 这种形状转成
    StageCredentials;raw 为 None(字段整个没给)时视为空配置。"""
    if raw is None:
        return StageCredentials()
    if not isinstance(raw, dict):
        raise HttpError(HTTPStatus.BAD_REQUEST, f"{field_name} 必须是一个对象")
    for key in ("model", "base_url", "api_key"):
        value = raw.get(key)
        if value is not None and not isinstance(value, str):
            raise HttpError(HTTPStatus.BAD_REQUEST, f"{field_name}.{key} 必须是字符串")
    return StageCredentials(
        model=(raw.get("model") or None),
        base_url=(raw.get("base_url") or None),
        api_key=(raw.get("api_key") or None),
    )


def _get_run(run_id: str) -> RunState:
    with RUNS_LOCK:
        run = RUNS.get(run_id)
    if run is None:
        raise HttpError(HTTPStatus.NOT_FOUND, f"run {run_id!r} 不存在")
    return run


def _emit(run: RunState, event: dict[str, Any]) -> None:
    with run.lock:
        run.events.append(event)
    run.new_event.set()


def _track_phase(run: RunState, stage_name: str) -> None:
    """按 Stage 的 before_stage 事件推进任务栏的阶段小圆点。

    看到某个阶段的 Stage 开始时,把它之前的阶段一律标记 done(哪怕是因为
    Breaker 短路、from 没有真正跑过 review 就直接进了 meta 这种情况——
    "之前的阶段"这个粒度不关心具体细节,只是给用户一个大致进度感),自己
    标记 active。
    """
    phase = PHASE_STAGE_MAP.get(stage_name)
    if phase is None:
        return
    with run.lock:
        if phase not in run.phases:
            return
        idx = run.phase_order.index(phase)
        for earlier in run.phase_order[:idx]:
            if run.phases[earlier] != "done":
                run.phases[earlier] = "done"
        run.phases[phase] = "active"


def _finalize_phases(run: RunState, status: str) -> None:
    """run 跑到终态时收尾阶段小圆点:成功则全部标 done;失败/终止则把当时
    正在进行的那个阶段标成 error,其余保持之前的状态不动。"""
    with run.lock:
        if status == "success":
            for phase in run.phase_order:
                run.phases[phase] = "done"
        else:
            for phase in run.phase_order:
                if run.phases[phase] == "active":
                    run.phases[phase] = "error"


def _make_checkpoint_handler(run: RunState):
    def handler(request: CheckpointRequest) -> dict[str, Any]:
        payload = {"name": request.name, "prompt": request.prompt, "context": request.context}
        with run.lock:
            run.pending_checkpoint = payload
            run.status = "awaiting_checkpoint"
            run.checkpoint_ready.clear()
        _emit(run, {"event": "checkpoint", **payload})

        run.checkpoint_ready.wait()  # 阻塞到 POST .../checkpoint 唤醒

        with run.lock:
            answer = run.checkpoint_answer or {"approved": False, "feedback": ""}
            run.pending_checkpoint = None
            run.status = "running"
        return answer

    return handler


def _after_stage(run: RunState, name: str, outputs: dict[str, Any]) -> None:
    _emit(run, {"event": "stage_done", "name": name})
    if name == "review":
        # 把审核发现的问题(字数是否达标、AI 修正错别字后的驳回结论)直接打
        # 到运行日志里,不然用户只能看到"[完成] review"这种空壳事件,不知道
        # 这一轮到底通过没通过、为什么被打回。
        review = outputs.get(REVIEW_PATH) or {}
        _emit(
            run,
            {
                "event": "review_result",
                "rejected": bool(review.get("rejected", False)),
                "feedback": review.get("feedback", ""),
            },
        )


def _before_stage(run: RunState, name: str) -> None:
    _track_phase(run, name)
    _emit(run, {"event": "stage_start", "name": name})


def _make_hooks(run: RunState) -> LifecycleHooks:
    return LifecycleHooks(
        before_stage=lambda name, _inputs: _before_stage(run, name),
        after_stage=lambda name, outputs: _after_stage(run, name, outputs),
        before_loop_iteration=lambda name, i: _emit(
            run, {"event": "loop_iteration", "name": name, "iteration": i + 1}
        ),
    )


def _run_thread(
    run: RunState,
    brief: dict[str, Any],
    default_credentials: StageCredentials,
    stage_credentials: dict[str, StageCredentials],
) -> None:
    output_dir = run.run_dir / "output"
    state_path = run.run_dir / STATE_FILENAME
    log_dir = (run.run_dir / "log") if LOG_CHATS else None
    try:
        result = run_workflow(
            brief,
            output_dir=output_dir,
            state_path=state_path,
            default_credentials=default_credentials,
            stage_credentials=stage_credentials,
            image_client=NotConfiguredImageClient(),
            checkpoint_handler=_make_checkpoint_handler(run),
            hooks=_make_hooks(run),
            # httpserver 不对外暴露续跑接口:每次提交都是一次全新的 run_id/
            # 状态文件,失败了就在前端看错误、改简介后重新提交。CLI 场景仍然
            # 支持续跑(见 scenarios/essay/run.py 的 --fresh 说明)。
            fresh=True,
            log_dir=log_dir,
        )
        with run.lock:
            run.status = "success"
            run.result = result
            # meta 节点这时已经跑完了,用它产出的正式标题替换掉创建时用
            # synopsis 顶的占位标题——任务栏要显示的是"这篇小说叫什么",
            # 不是简介的前 24 个字。
            meta_title = ((result or {}).get("meta") or {}).get("title")
            if meta_title:
                run.title = meta_title
        _finalize_phases(run, "success")
        _emit(run, {"event": "done", "status": "success"})
    except PlanningRejectedError as err:
        with run.lock:
            run.status = "terminated_rejected"
            run.error = str(err)
        _finalize_phases(run, "terminated_rejected")
        _emit(run, {"event": "done", "status": "terminated_rejected", "message": str(err)})
    except Exception as err:  # noqa: BLE001 —— 后台线程的兜底,不能让异常静默丢失
        with run.lock:
            run.status = "failed"
            run.error = repr(err)
        _finalize_phases(run, "failed")
        _emit(run, {"event": "done", "status": "failed", "message": repr(err)})


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    server_version = "EssayHTTP/0.1"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
        pass  # 默认会把每个请求打到 stderr,静默掉避免刷屏

    # -- 公共 -----------------------------------------------------------------

    def _send_json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw or b"{}")
        except json.JSONDecodeError as exc:
            raise HttpError(HTTPStatus.BAD_REQUEST, f"请求体不是合法 JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise HttpError(HTTPStatus.BAD_REQUEST, "请求体必须是一个 JSON 对象")
        return data

    # -- 分发 -----------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 - stdlib method name
        try:
            self._route_get()
        except HttpError as err:
            self._send_json(err.status, {"error": err.message})

    def do_POST(self) -> None:  # noqa: N802
        try:
            self._route_post()
        except HttpError as err:
            self._send_json(err.status, {"error": err.message})

    def _route_get(self) -> None:
        path = urlparse(self.path).path
        if path in STATIC_FILES:
            self._serve_static(path)
            return
        if path == "/api/monthly-trends":
            self._send_json(HTTPStatus.OK, {"options": load_monthly_trend_options()})
            return
        if path == "/api/runs":
            self._send_json(HTTPStatus.OK, {"runs": _list_runs_payload()})
            return
        match = _RUN_GET_RE.match(path)
        if match:
            run_id, action = match.groups()
            run = _get_run(run_id)
            if action == "status":
                self._send_json(HTTPStatus.OK, _status_payload(run))
            elif action == "events":
                self._serve_events(run)
            elif action == "download":
                self._serve_download(run)
            elif action == "state":
                self._serve_state(run)
            else:
                self._serve_result(run)
            return
        raise HttpError(HTTPStatus.NOT_FOUND, "not found")

    def _route_post(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/runs":
            self._handle_create_run()
            return
        match = _RUN_CHECKPOINT_RE.match(path)
        if match:
            self._handle_checkpoint(_get_run(match.group(1)))
            return
        raise HttpError(HTTPStatus.NOT_FOUND, "not found")

    # -- 静态文件 --------------------------------------------------------------

    def _serve_static(self, path: str) -> None:
        filename, content_type = STATIC_FILES[path]
        file_path = STATIC_DIR / filename
        body = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # -- runs -------------------------------------------------------------

    def _handle_create_run(self) -> None:
        body = self._read_json_body()

        brief_raw = body.get("brief")
        if not isinstance(brief_raw, dict):
            raise HttpError(HTTPStatus.BAD_REQUEST, "brief 必须是一个对象")
        try:
            # 校验通过后拿到补全默认值的规范化 brief——既传给 run_workflow
            # (它内部会再校验一遍,parse_brief 是幂等的,无害),也存进
            # RunState 供任务栏/任务详情展示用(不含任何 model/API Key)。
            brief = parse_brief(brief_raw)
        except ValueError as err:
            raise HttpError(HTTPStatus.BAD_REQUEST, str(err)) from err

        # 默认模型配置是必填的(model/base_url/api_key 三者都要有),各环节
        # (planning/drafting/review/cover)可以选填覆盖,省下的字段退回默认。
        default_credentials = _credentials_from_body(body.get("default"), field_name="default")
        if not (default_credentials.model and default_credentials.base_url and default_credentials.api_key):
            raise HttpError(HTTPStatus.BAD_REQUEST, "default.model / default.base_url / default.api_key 都是必填项")

        stages_raw = body.get("stages") or {}
        if not isinstance(stages_raw, dict):
            raise HttpError(HTTPStatus.BAD_REQUEST, "stages 必须是一个对象")
        unknown_stages = sorted(set(stages_raw) - set(STAGE_NAMES))
        if unknown_stages:
            raise HttpError(HTTPStatus.BAD_REQUEST, f"stages 包含未知环节: {unknown_stages}")
        stage_credentials = {
            stage: _credentials_from_body(stages_raw.get(stage), field_name=f"stages.{stage}")
            for stage in STAGE_NAMES
        }

        run_id = time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
        phase_order = _phase_order_for(brief)
        run = RunState(
            run_id=run_id,
            run_dir=RUNS_DIR / run_id,
            brief=brief,
            title=_title_from_synopsis(brief["synopsis"]),
            phase_order=phase_order,
            phases={phase: "pending" for phase in phase_order},
        )
        with RUNS_LOCK:
            RUNS[run_id] = run

        thread = threading.Thread(
            target=_run_thread,
            args=(run, brief, default_credentials, stage_credentials),
            daemon=True,
        )
        thread.start()

        self._send_json(HTTPStatus.OK, {"run_id": run_id})

    def _serve_events(self, run: RunState) -> None:
        # SSE 没有 Content-Length,浏览器的 EventSource 靠"连接一直开着"识别流
        # 还没结束;但这里我们是有限流(run 结束就没有更多事件了),所以显式
        # 关闭连接而不是 keep-alive——否则非浏览器客户端(比如测试用的
        # urllib)会一直等下一条数据,直到超时。
        self.close_connection = True
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        index = 0
        try:
            while True:
                with run.lock:
                    pending = run.events[index:]
                    index = len(run.events)
                    status = run.status
                for event in pending:
                    self.wfile.write(f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode("utf-8"))
                if pending:
                    self.wfile.flush()
                if status in TERMINAL_STATUSES:
                    break
                run.new_event.wait(timeout=15)
                run.new_event.clear()
        except (BrokenPipeError, ConnectionResetError):
            pass  # 浏览器关闭了连接,不是服务端的错误

    def _serve_result(self, run: RunState) -> None:
        with run.lock:
            status = run.status
            result = run.result
            error = run.error
        if status not in TERMINAL_STATUSES:
            raise HttpError(HTTPStatus.CONFLICT, "任务尚未结束")
        if status == "success":
            self._send_json(HTTPStatus.OK, result)
        else:
            self._send_json(HTTPStatus.OK, {"status": status, "error": error})

    def _serve_download(self, run: RunState) -> None:
        with run.lock:
            status = run.status
            result = run.result
        if status != "success":
            raise HttpError(HTTPStatus.CONFLICT, "任务尚未成功完成,暂时没有可下载的产物")
        manuscript_path = Path(result["manuscript_path"])
        body = manuscript_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/markdown; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="{run.run_id}.md"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_state(self, run: RunState) -> None:
        # 不按 run.status 门控:卡住/失败的 run 恰恰是最需要看状态快照排查的
        # 场景,不能等到 success 才让下载——JsonFileStateStore 每完成一个节点
        # 就落盘一次,文件在跑到一半时就已经存在且有内容。
        state_path = run.run_dir / STATE_FILENAME
        if not state_path.is_file():
            raise HttpError(HTTPStatus.NOT_FOUND, "状态文件尚未生成")
        body = state_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="{run.run_id}_state.json"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_checkpoint(self, run: RunState) -> None:
        body = self._read_json_body()
        approved = body.get("approved")
        if not isinstance(approved, bool):
            raise HttpError(HTTPStatus.BAD_REQUEST, "approved 必须是 true/false")
        with run.lock:
            if run.status != "awaiting_checkpoint":
                raise HttpError(HTTPStatus.CONFLICT, "当前没有待处理的人工审核")
            run.checkpoint_answer = {"approved": approved, "feedback": str(body.get("feedback", ""))}
        run.checkpoint_ready.set()
        self._send_json(HTTPStatus.OK, {"ok": True})


def _status_payload(run: RunState) -> dict[str, Any]:
    with run.lock:
        payload: dict[str, Any] = {
            "run_id": run.run_id,
            "status": run.status,
            "title": run.title,
            "brief": run.brief,
            "phase_order": list(run.phase_order),
            "phases": dict(run.phases),
        }
        if run.pending_checkpoint:
            payload["checkpoint"] = run.pending_checkpoint
        if run.error:
            payload["error"] = run.error
    return payload


def _list_runs_payload() -> list[dict[str, Any]]:
    """任务栏轮盘用的轻量列表:不带 brief(点开某个任务时再用 /status 单独
    取详情),只给球体渲染需要的最少信息,按创建时间升序排列。"""
    with RUNS_LOCK:
        runs = list(RUNS.values())
    runs.sort(key=lambda r: r.created_at)
    payload = []
    for run in runs:
        with run.lock:
            payload.append(
                {
                    "run_id": run.run_id,
                    "status": run.status,
                    "title": run.title,
                    "created_at": run.created_at,
                    "phase_order": list(run.phase_order),
                    "phases": dict(run.phases),
                }
            )
    return payload


def main() -> None:
    global LOG_CHATS

    parser = argparse.ArgumentParser(description="essay 场景的本地 Web 界面")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--log-chats",
        action="store_true",
        help="把每个 run 每次 chat() 的请求/响应(含 stop_reason)落盘到 runs/<run_id>/log/,用于排查生成内容异常",
    )
    args = parser.parse_args()
    LOG_CHATS = args.log_chats

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    _load_runs_from_disk()
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"essay httpserver listening on http://{args.host}:{args.port} ({len(RUNS)} 个历史任务已重新挂载)")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
