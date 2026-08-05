"""short 场景的运行入口。

组装 LLMClient / StateStore / RunContext,跑通 workflow.py 的 build_workflow()
拼出的流程,最后把成品落地成 Markdown/JSON。全程无人工断点,启动后不需要有人守着。

用法:

    # 先看看要填哪些设定
    python -m scenarios.short.run --show-fields

    # 改好 scenarios/short/brief.yaml 之后跑
    OPENAI_API_KEY=sk-... SHORT_MODEL=qwen3.7-max \\
        python -m scenarios.short.run --output-dir scenarios/short/output --log-chats

中途失败时,状态与"从哪个顶层节点续跑"会被保存下来,修好问题后重跑同一条命令
即可接着走,不必从头再生成一遍。
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from engine.context import LifecycleHooks, ResumePoint, RunContext
from engine.workflow import WorkflowFailure
from llm.client import LLMClient
from llm.logging_client import LoggingLLMClient
from state.backends.json_file import JsonFileStateStore

from scenarios.short.brief import describe_fields, load_brief
from scenarios.short.landing import land_output
from scenarios.short.state_schema import empty_state
from scenarios.short.workflow import build_workflow

DEFAULT_BRIEF_PATH = Path(__file__).with_name("brief.yaml")
DEFAULT_OUTPUT_DIR = Path(__file__).with_name("output")
DEFAULT_STATE_FILE = "short_story_state.json"
RESUME_SUFFIX = ".resume.json"

_PROVIDER_DEFAULT_MODEL = {"anthropic": "claude-sonnet-latest", "openai": "gpt-4o", "zhipu": "glm-5.2"}
_PROVIDER_API_KEY_ENV = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "zhipu": "ZHIPU_API_KEY"}


# ---------------------------------------------------------------------------
# 续跑点:顶层节点游标 + 流入的 inputs(state 本身由 JsonFileStateStore 每次
# patch 时就已落盘,这里只补它盖不住的那部分)。手法与 scenarios/novel 一致。
# ---------------------------------------------------------------------------


def _resume_path(state_path: Path) -> Path:
    return state_path.with_name(state_path.name + RESUME_SUFFIX)


def _save_resume_point(state_path: Path, node_index: int, inputs: dict[str, Any], node_name: str) -> None:
    resume_path = _resume_path(state_path)
    resume_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = resume_path.with_name(resume_path.name + ".tmp")
    payload = {"node_index": node_index, "node_name": node_name, "inputs": inputs}
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    tmp_path.replace(resume_path)


def _load_resume_point(state_path: Path) -> ResumePoint | None:
    resume_path = _resume_path(state_path)
    if not resume_path.exists():
        return None
    with resume_path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    return ResumePoint(node_index=payload["node_index"], inputs=payload["inputs"])


def _clear_resume_point(state_path: Path) -> None:
    _resume_path(state_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# LLMClient
# ---------------------------------------------------------------------------


def _infer_provider(model: str) -> str:
    """按模型名判断该用哪家 SDK:claude-* 走 Anthropic,glm-* 走智谱,其余走 OpenAI 兼容协议。"""
    if model.startswith("claude"):
        return "anthropic"
    if model.startswith("glm"):
        return "zhipu"
    return "openai"


def build_llm_client(model: str | None = None, log_dir: Path | None = None) -> LLMClient:
    """按 model(若给出)或环境变量选一个 Provider 并构造 client。

    Args:
        model: 本次要用的模型名。给出时由 _infer_provider 按模型名决定 Provider
            ——模型与 Provider 是绑死的,不是"哪个 API Key 恰好存在"能替代的。
            为 None 时按环境变量里存在哪个 API Key 决定,模型名退回 SHORT_MODEL
            环境变量或该 Provider 的默认值。
        log_dir: 非 None 时包一层 LoggingLLMClient,把每次 chat() 落盘。
    """
    if model is not None:
        provider = _infer_provider(model)
    elif os.environ.get("ANTHROPIC_API_KEY"):
        provider = "anthropic"
    elif os.environ.get("OPENAI_API_KEY"):
        provider = "openai"
    elif os.environ.get("ZHIPU_API_KEY"):
        provider = "zhipu"
    else:
        raise RuntimeError("需要设置 ANTHROPIC_API_KEY / OPENAI_API_KEY / ZHIPU_API_KEY 之一才能运行本场景。")

    api_key_env = _PROVIDER_API_KEY_ENV[provider]
    api_key = os.environ.get(api_key_env)
    if not api_key:
        raise RuntimeError(f"使用模型 {model!r} 需要 {provider} 的 SDK,但当前环境未设置 {api_key_env}。")
    resolved_model = model or os.environ.get("SHORT_MODEL", _PROVIDER_DEFAULT_MODEL[provider])

    if provider == "anthropic":
        from llm.providers.anthropic import AnthropicClient

        client: LLMClient = AnthropicClient(
            api_key=api_key,
            model=resolved_model,
            base_url=os.environ.get("ANTHROPIC_API_BASE_URL"),
            max_tokens=16384,
        )
    elif provider == "zhipu":
        from llm.providers.zhipu import ZhipuClient

        client = ZhipuClient(
            api_key=api_key,
            model=resolved_model,
            base_url=os.environ.get("ZHIPU_API_BASE_URL"),
            max_tokens=16384,
        )
    else:
        from llm.providers.openai import OpenAIClient

        client = OpenAIClient(
            api_key=api_key,
            model=resolved_model,
            base_url=os.environ.get("OPENAI_API_BASE_URL"),
            max_tokens=16384,
        )

    if log_dir is not None:
        client = LoggingLLMClient(client, log_dir)
    return client


def make_client_factory(model: str | None = None, log_dir: Path | None = None):
    """按 model 分组、按需惰性构造并复用 LLMClient。

    workflow.py 里没有任何节点显式指定 model,所以正常情况下所有节点共用同一个
    client;要给某个节点换模型,在 workflow.py 对应的 client_for(...) 调用里传
    model 即可,这里不用动。
    """
    clients: dict[str | None, LLMClient] = {}

    def factory(_stage_name: str, stage_model: str | None) -> LLMClient:
        key = stage_model or model
        if key not in clients:
            clients[key] = build_llm_client(key, log_dir)
        return clients[key]

    return factory


def main() -> None:
    parser = argparse.ArgumentParser(description="生成一篇 8000-10000 字的短篇网络小说")
    parser.add_argument("--brief", type=Path, default=DEFAULT_BRIEF_PATH, help="用户设定 yaml 路径")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="落地产物目录")
    parser.add_argument("--state-file", type=Path, default=None, help="状态文件路径(默认写到 --output-dir 下)")
    parser.add_argument("--model", default=None, help="本次使用的模型名(默认取 SHORT_MODEL 环境变量)")
    parser.add_argument("--log-chats", action="store_true", help="把每次 chat() 的请求/响应落盘到 output/log")
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="丢弃已有状态,从零重新生成一篇(不加这个参数时会尝试接着上次的进度跑)",
    )
    parser.add_argument("--show-fields", action="store_true", help="打印可填的设定项清单后退出")
    args = parser.parse_args()

    if args.show_fields:
        print(describe_fields())
        return

    # 先校验用户设定再建 client:设定写错时应该立刻报错,而不是跑到第一个节点
    # 才失败(那时已经建好了连接、可能也已经产生了费用)。
    brief = load_brief(args.brief)

    log_dir = (args.output_dir / "log") if args.log_chats else None
    workflow = build_workflow(client_factory=make_client_factory(args.model, log_dir))

    state_path = args.state_file or (args.output_dir / DEFAULT_STATE_FILE)
    state_store = JsonFileStateStore(state_path)
    # 上一次跑完的状态里,ForEach 的游标停在最后一节之后(那是断点续跑赖以工作
    # 的机制,见 engine/primitives/foreach.py)。所以对着一份已完成的状态再跑一次
    # 不会重写一篇新的,而是什么都不做 —— 想重新生成得显式 --fresh。
    if args.fresh:
        state_store.load(empty_state())
        _clear_resume_point(state_path)
    elif not state_store.snapshot():
        state_store.load(empty_state())

    resume = _load_resume_point(state_path)
    if resume is not None:
        print(f"检测到上次未完成的运行,从顶层节点游标 {resume.node_index} 续跑,跳过已成功的前序节点。")

    ctx = RunContext(
        state=state_store,
        hooks=LifecycleHooks(
            before_stage=lambda name, _inputs: print(f"[stage:start] {name}"),
            after_stage=lambda name, _outputs: print(f"[stage:done]  {name}"),
            before_loop_iteration=lambda name, i: print(f"[loop] {name} 第 {i + 1} 轮"),
        ),
        resume=resume,
    )

    try:
        outputs = workflow.run(ctx, brief)
    except WorkflowFailure as failure:
        _save_resume_point(state_path, failure.node_index, failure.inputs, failure.node_name)
        land_output(state_store.snapshot(), args.output_dir)
        print(
            f"流程在节点 {failure.node_name!r}(顶层游标 {failure.node_index})执行失败:"
            f"{failure.__cause__!r}\n状态已保存到 {state_path},修复后重跑本命令即可从该节点续跑。"
        )
        raise

    _clear_resume_point(state_path)
    qa_report = outputs.get("qa_report") or {}
    written = land_output(state_store.snapshot(), args.output_dir, qa_report)
    print("\n已落地产物:")
    for label, path in written.items():
        print(f"  {label}: {path}")
    print(
        f"\n终检:全文 {qa_report.get('total_word_count')} 字 / 目标 "
        f"{qa_report.get('target_word_count')},达标={qa_report.get('in_target_range')}"
    )
    flagged = [str(s.get("index")) for s in qa_report.get("sections") or [] if s.get("style_violations")]
    if flagged:
        print(f"以下小节的文风体检仍有越界项,建议人工过一遍:第 {'、'.join(flagged)} 节")


if __name__ == "__main__":
    main()
