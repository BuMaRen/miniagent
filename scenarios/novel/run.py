"""novel 场景的真实运行入口(docs/framework-design.md §8 步骤 5)。

组装 LLMClient / StateStore / RunContext,跑通 workflow.yaml 定义的流程,
最后把故事圣经"落地"成 Markdown/JSON 文件。需要设置 ANTHROPIC_API_KEY 或
OPENAI_API_KEY 环境变量;没有 API Key 时,可以运行同目录下的
offline_demo.py 用脚本化回复走一遍完整流水线,验证接线是否正确。

用法示例:

    ANTHROPIC_API_KEY=sk-... python -m scenarios.novel.run \\
        --output-dir scenarios/novel/output --auto-approve
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

import yaml

from engine.context import CheckpointRequest, LifecycleHooks, RunContext
from engine.primitives.checkpoint import CheckpointPause
from llm.client import LLMClient
from state.backends.json_file import JsonFileStateStore

from scenarios.novel.landing import land_output
from scenarios.novel.state_schema import empty_state
from scenarios.novel.workflow import build_workflow

DEFAULT_BRIEF_PATH = Path(__file__).with_name("brief.yaml")
DEFAULT_OUTPUT_DIR = Path(__file__).with_name("output")
DEFAULT_STATE_FILE = "story_bible_state.json"


def build_llm_client() -> LLMClient:
    """按环境变量选一个真实 Provider;优先 Anthropic,其次 OpenAI。"""
    if os.environ.get("ANTHROPIC_API_KEY"):
        from llm.providers.anthropic import AnthropicClient

        return AnthropicClient(
            api_key=os.environ["ANTHROPIC_API_KEY"],
            model=os.environ.get("NOVEL_MODEL", "claude-sonnet-4-5"),
        )
    if os.environ.get("OPENAI_API_KEY"):
        from llm.providers.openai import OpenAIClient

        return OpenAIClient(
            api_key=os.environ["OPENAI_API_KEY"],
            model=os.environ.get("NOVEL_MODEL", "gpt-4o"),
        )
    raise RuntimeError(
        "需要设置 ANTHROPIC_API_KEY 或 OPENAI_API_KEY 才能真实运行本场景;"
        "没有 API Key 时,可运行 `python -m scenarios.novel.offline_demo` "
        "用脚本化回复体验完整流水线(见 scenarios/novel/README.md)。"
    )


def make_checkpoint_handler(auto_approve: bool):
    """CLI 版 CheckpointHandler:大纲确认走交互式确认(或 --auto-approve 自动通过),
    Loop 超限升级的断点默认接受最后一版并打印提示,供人工事后复核。"""

    def handler(request: CheckpointRequest) -> dict[str, Any]:
        print(f"\n=== Checkpoint: {request.name} ===")
        if request.prompt:
            print(request.prompt)
        if request.name == "confirm_outline":
            if auto_approve:
                print("[auto] 已自动确认大纲,继续执行。")
                return {"approved": True}
            answer = input("是否批准当前大纲? [y/N] ").strip().lower()
            return {"approved": answer == "y"}
        print("[warn] Loop 已达最大迭代次数仍未通过评审,自动接受最后一版,请事后复核。")
        return request.context or {}

    return handler


def load_brief(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main() -> None:
    parser = argparse.ArgumentParser(description="运行 novel 场景的完整生成流水线")
    parser.add_argument("--brief", type=Path, default=DEFAULT_BRIEF_PATH, help="StoryBrief yaml 路径")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="落地产物目录")
    parser.add_argument(
        "--state-file",
        type=Path,
        default=None,
        help="状态持久化文件路径(默认写到 --output-dir 下),支持断点续跑",
    )
    parser.add_argument(
        "--auto-approve", action="store_true", help="大纲确认断点自动通过,不进入交互式输入"
    )
    args = parser.parse_args()

    brief = load_brief(args.brief)
    client = build_llm_client()
    workflow = build_workflow(client_factory=lambda _stage_name: client)

    state_path = args.state_file or (args.output_dir / DEFAULT_STATE_FILE)
    state_store = JsonFileStateStore(state_path)
    if not state_store.snapshot():
        state_store.load(empty_state())

    ctx = RunContext(
        state=state_store,
        checkpoint_handler=make_checkpoint_handler(args.auto_approve),
        hooks=LifecycleHooks(
            before_stage=lambda name, _inputs: print(f"[stage:start] {name}"),
            after_stage=lambda name, _outputs: print(f"[stage:done]  {name}"),
        ),
    )

    try:
        outputs = workflow.run(ctx, brief)
    except CheckpointPause as pause:
        print(f"流程在断点 {pause.checkpoint_name!r} 处暂停,状态已保存到 {state_path},可稍后续跑。")
        return

    written = land_output(state_store.snapshot(), args.output_dir)
    print("\n已落地产物:")
    for label, path in written.items():
        print(f"  {label}: {path}")
    print("\nfinal_qa 报告:", outputs.get("qa_report"))


if __name__ == "__main__":
    main()
