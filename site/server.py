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

STATIC_DIR = Path(__file__).with_name("static")
RUNS_DIR = Path(__file__).with_name("runs")
STATE_FILENAME = "essay_state.json"

# 由 --log-chats 命令行开关控制,main() 里按需改写;开启后每个 run 的每次
# chat() 请求/响应(含 stop_reason)会落到 run_dir/log/chat_NNNN.json,供事后
# 排查"内容被截断"这类只看最终产物猜不出原因的问题(见 llm/logging_client.py)。
LOG_CHATS = False

TERMINAL_STATUSES = {"success", "failed", "terminated_rejected"}

STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
}

_RUN_GET_RE = re.compile(r"^/api/runs/([^/]+)/(status|events|result|download|state)$")
_RUN_CHECKPOINT_RE = re.compile(r"^/api/runs/([^/]+)/checkpoint$")


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
    status: str = "running"  # running | awaiting_checkpoint | success | failed | terminated_rejected
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


def _make_hooks(run: RunState) -> LifecycleHooks:
    return LifecycleHooks(
        before_stage=lambda name, _inputs: _emit(run, {"event": "stage_start", "name": name}),
        after_stage=lambda name, _outputs: _emit(run, {"event": "stage_done", "name": name}),
        before_loop_iteration=lambda name, i: _emit(
            run, {"event": "loop_iteration", "name": name, "iteration": i + 1}
        ),
    )


def _run_thread(
    run: RunState,
    brief_raw: dict[str, Any],
    default_credentials: StageCredentials,
    stage_credentials: dict[str, StageCredentials],
) -> None:
    output_dir = run.run_dir / "output"
    state_path = run.run_dir / STATE_FILENAME
    log_dir = (run.run_dir / "log") if LOG_CHATS else None
    try:
        result = run_workflow(
            brief_raw,
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
        _emit(run, {"event": "done", "status": "success"})
    except PlanningRejectedError as err:
        with run.lock:
            run.status = "terminated_rejected"
            run.error = str(err)
        _emit(run, {"event": "done", "status": "terminated_rejected", "message": str(err)})
    except Exception as err:  # noqa: BLE001 —— 后台线程的兜底,不能让异常静默丢失
        with run.lock:
            run.status = "failed"
            run.error = repr(err)
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
            parse_brief(brief_raw)  # 提前校验,写错的简介立刻在提交时报错。
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
        run = RunState(run_id=run_id, run_dir=RUNS_DIR / run_id)
        with RUNS_LOCK:
            RUNS[run_id] = run

        thread = threading.Thread(
            target=_run_thread,
            args=(run, brief_raw, default_credentials, stage_credentials),
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
        payload: dict[str, Any] = {"run_id": run.run_id, "status": run.status}
        if run.pending_checkpoint:
            payload["checkpoint"] = run.pending_checkpoint
        if run.error:
            payload["error"] = run.error
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
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"essay httpserver listening on http://{args.host}:{args.port}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
