"""short 场景的 Web 化生产界面 —— 后端入口。

把 `python -m scenarios.short.run` 这条命令行流程包一层浏览器可访问的 HTTP 服务:
网页表单 -> 校验 -> 一次 subprocess 调用,再把 subprocess 的 stdout 转成 SSE 推给浏览器。

不引入 Flask/FastAPI 等新依赖(仓库里没装任何 web 框架),用标准库
`http.server.ThreadingHTTPServer` 自己写路由分发。不改动 scenarios/short 或框架层任何代码,
只通过 run.py 现有的 CLI 参数(--brief --output-dir --model --fresh --log-chats)集成。

启动:
    python site/server.py [--host 0.0.0.0] [--port 8000]
"""

from __future__ import annotations

import argparse
import dataclasses
import io
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
import zipfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# 运行时才把仓库根目录挂到 sys.path,不用 PYTHONPATH 环境变量 —— 避免子进程
# 或本进程解释器启动阶段的自动 `import site` 被 site/ 目录本身遮蔽(此时标准库
# site 模块早已在 sys.modules 里缓存,运行期 insert 不会有影响)。
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scenarios.short.brief import BRIEF_FIELDS, parse_brief  # noqa: E402

STATIC_DIR = Path(__file__).with_name("static")
RUNS_DIR = Path(__file__).with_name("runs")

_PROVIDER_API_KEY_ENV = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}
_PROVIDER_BASE_URL_ENV = {"anthropic": "ANTHROPIC_API_BASE_URL", "openai": "OPENAI_API_BASE_URL"}

STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}


def _infer_provider(model: str) -> str:
    """与 scenarios/short/run.py 里同名函数保持一致的判定规则。"""
    return "anthropic" if model.startswith("claude") else "openai"


# ---------------------------------------------------------------------------
# 运行态
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class RunState:
    run_id: str
    run_dir: Path
    process: subprocess.Popen
    lines: list[str] = dataclasses.field(default_factory=list)
    status: str = "running"  # running | success | failed
    exit_code: int | None = None
    lock: threading.Lock = dataclasses.field(default_factory=threading.Lock)


RUNS: dict[str, RunState] = {}
RUNS_GLOBAL_LOCK = threading.Lock()  # 保证同一时间只有一个任务在跑


def _reader_thread(run: RunState) -> None:
    assert run.process.stdout is not None
    for raw_line in run.process.stdout:
        line = raw_line.rstrip("\n")
        with run.lock:
            run.lines.append(line)
    run.process.wait()
    with run.lock:
        run.exit_code = run.process.returncode
        run.status = "success" if run.exit_code == 0 else "failed"
    terminal_log = run.run_dir / "output" / "terminal.log"
    terminal_log.parent.mkdir(parents=True, exist_ok=True)
    terminal_log.write_text("\n".join(run.lines) + "\n", encoding="utf-8")
    RUNS_GLOBAL_LOCK.release()


def start_run(token: str, base_url: str, model: str, brief_raw: dict[str, Any]) -> str:
    """校验 brief、落盘、拉起 subprocess。抛 ValueError / RuntimeError 由调用方转成 HTTP 错误。"""
    brief = parse_brief(brief_raw)  # 复用 brief.py 的校验,失败时中文错误直接透传

    if not model or not model.strip():
        raise ValueError("model 不能为空")
    model = model.strip()
    if not token or not token.strip():
        raise ValueError("API Key 不能为空")

    if not RUNS_GLOBAL_LOCK.acquire(blocking=False):
        raise RuntimeError("已有任务正在运行,请等它跑完再提交新任务。")

    try:
        run_id = time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
        run_dir = RUNS_DIR / run_id
        output_dir = run_dir / "output"
        run_dir.mkdir(parents=True)

        import yaml

        brief_path = run_dir / "brief.yaml"
        brief_path.write_text(yaml.safe_dump(brief, allow_unicode=True, sort_keys=False), encoding="utf-8")

        provider = _infer_provider(model)
        env = os.environ.copy()
        env[_PROVIDER_API_KEY_ENV[provider]] = token.strip()
        if base_url and base_url.strip():
            env[_PROVIDER_BASE_URL_ENV[provider]] = base_url.strip()

        process = subprocess.Popen(
            [
                sys.executable,
                "-u",  # 子进程的 stdout 不是 tty,不加 -u 会整块缓冲,进度没法实时推给前端
                "-m",
                "scenarios.short.run",
                "--brief",
                str(brief_path),
                "--output-dir",
                str(output_dir),
                "--model",
                model,
                "--fresh",
                "--log-chats",
            ],
            cwd=str(REPO_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        run = RunState(run_id=run_id, run_dir=run_dir, process=process)
        RUNS[run_id] = run
        threading.Thread(target=_reader_thread, args=(run,), daemon=True).start()
        return run_id
    except BaseException:
        RUNS_GLOBAL_LOCK.release()
        raise


# ---------------------------------------------------------------------------
# 下载打包
# ---------------------------------------------------------------------------


def _zip_bytes(files: list[tuple[str, Path]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for arcname, path in files:
            if path.is_file():
                zf.write(path, arcname)
    return buf.getvalue()


def build_product_zip(run: RunState) -> bytes:
    output_dir = run.run_dir / "output"
    files = [
        ("story.md", output_dir / "story.md"),
        ("outline.md", output_dir / "outline.md"),
        ("qa_report.json", output_dir / "qa_report.json"),
    ]
    return _zip_bytes(files)


def build_debug_zip(run: RunState) -> bytes:
    output_dir = run.run_dir / "output"
    files: list[tuple[str, Path]] = []
    if output_dir.is_dir():
        for path in output_dir.rglob("*"):
            if path.is_file():
                files.append((str(path.relative_to(output_dir)), path))
    return _zip_bytes(files)


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

_RUN_ID_RE = re.compile(r"^/api/run/([^/]+)/(events|status|download/product|download/debug)$")


class Handler(BaseHTTPRequestHandler):
    server_version = "ShortStorySite/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:  # 不用默认的 stderr 单行格式,静默掉噪音
        pass

    # -- helpers --------------------------------------------------------

    def _send_json(self, status: HTTPStatus, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, status: HTTPStatus, body: bytes, content_type: str, extra_headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> Any:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw or b"{}")

    # -- routing ----------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path

        if path in STATIC_FILES:
            self._serve_static(path)
            return

        if path == "/api/brief-fields":
            self._send_json(
                HTTPStatus.OK,
                [
                    {"name": f.name, "required": f.required, "default": f.default, "kind": f.kind, "note": f.note}
                    for f in BRIEF_FIELDS
                ],
            )
            return

        match = _RUN_ID_RE.match(path)
        if match:
            run_id, action = match.group(1), match.group(2)
            run = RUNS.get(run_id)
            if run is None:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": f"未找到任务 {run_id}"})
                return
            if action == "events":
                self._stream_events(run)
            elif action == "status":
                with run.lock:
                    self._send_json(HTTPStatus.OK, {"status": run.status, "exit_code": run.exit_code})
            elif action == "download/product":
                data = build_product_zip(run)
                self._send_bytes(
                    HTTPStatus.OK, data, "application/zip",
                    {"Content-Disposition": f'attachment; filename="{run_id}_story.zip"'},
                )
            elif action == "download/debug":
                data = build_debug_zip(run)
                self._send_bytes(
                    HTTPStatus.OK, data, "application/zip",
                    {"Content-Disposition": f'attachment; filename="{run_id}_debug.zip"'},
                )
            return

        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path != "/api/run":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return

        try:
            payload = self._read_json_body()
            run_id = start_run(
                token=payload.get("token", ""),
                base_url=payload.get("base_url", ""),
                model=payload.get("model", ""),
                brief_raw=payload.get("brief", {}),
            )
            self._send_json(HTTPStatus.OK, {"run_id": run_id})
        except ValueError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except RuntimeError as exc:
            self._send_json(HTTPStatus.CONFLICT, {"error": str(exc)})

    # -- implementations ----------------------------------------------------

    def _serve_static(self, path: str) -> None:
        filename, content_type = STATIC_FILES[path]
        file_path = STATIC_DIR / filename
        if not file_path.is_file():
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "static file missing"})
            return
        self._send_bytes(HTTPStatus.OK, file_path.read_bytes(), content_type)

    def _stream_events(self, run: RunState) -> None:
        # 响应没有 Content-Length/chunked 分帧,唯一的"结束"信号就是关闭连接 ——
        # 不能回 keep-alive,否则客户端会在 done 之后继续挂着等下一段字节。
        self.close_connection = True
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        sent = 0
        try:
            while True:
                with run.lock:
                    pending = run.lines[sent:]
                    sent = len(run.lines)
                    status, exit_code = run.status, run.exit_code
                for line in pending:
                    self.wfile.write(f"data: {line}\n\n".encode("utf-8"))
                self.wfile.flush()
                if status != "running" and sent >= len(run.lines):
                    self.wfile.write(f"event: done\ndata: {exit_code}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    break
                time.sleep(0.3)
        except (BrokenPipeError, ConnectionResetError):
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description="short 场景的 Web 生产界面")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址(默认 0.0.0.0,局域网可访问)")
    parser.add_argument("--port", type=int, default=8000, help="监听端口(默认 8000)")
    args = parser.parse_args()

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"short 场景生产界面已启动:http://{args.host}:{args.port}/ (Ctrl+C 停止)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
