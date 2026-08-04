"""novel 场景的真实运行入口(docs/framework-design.md §8 步骤 5)。

组装 LLMClient / StateStore / RunContext,跑通 workflow.yaml 定义的流程,
最后把故事圣经"落地"成 Markdown/JSON 文件。需要设置 ANTHROPIC_API_KEY 或
OPENAI_API_KEY 环境变量;没有 API Key 时,可以运行同目录下的
offline_demo.py 用脚本化回复走一遍完整流水线,验证接线是否正确。

用法示例:

    ANTHROPIC_API_KEY=sk-... python -m scenarios.novel.run \\
        --output-dir scenarios/novel/output --auto-approve --log-chats
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import yaml

from engine.context import CheckpointRequest, LifecycleHooks, ResumePoint, RunContext
from engine.workflow import WorkflowFailure
from llm.client import LLMClient
from llm.logging_client import LoggingLLMClient
from state.backends.json_file import JsonFileStateStore

from scenarios.novel import SCENARIO
from scenarios.novel.executors import NEEDS_REVISION_KEY
from scenarios.novel.landing import land_output

DEFAULT_BRIEF_PATH = Path(__file__).with_name("brief.yaml")
DEFAULT_OUTPUT_DIR = Path(__file__).with_name("output")
DEFAULT_STATE_FILE = "story_bible_state.json"
RESUME_SUFFIX = ".resume.json"


def _resume_path(state_path: Path) -> Path:
    return state_path.with_name(state_path.name + RESUME_SUFFIX)


def _save_resume_point(state_path: Path, node_index: int, inputs: dict[str, Any], node_name: str) -> None:
    """把"从哪个顶层节点续跑"记到 state 文件旁的一份 sidecar JSON 里。

    state_store 本身每次 patch/append 都已落盘(见 JsonFileStateStore),但那只是
    各 Stage 通过 writes 显式写回的状态切片;顶层节点游标与直接透传的 outputs
    (§7.2 通道①,不落 State)不在其中,必须单独持久化,下次启动才能定位到
    "重跑这个节点、之前的都不用再跑一遍"。
    """
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


_PROVIDER_DEFAULT_MODEL = {"anthropic": "claude-sonnet-latest", "openai": "gpt-4o", "zhipu": "glm-5.2"}
_PROVIDER_API_KEY_ENV = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "zhipu": "ZHIPU_API_KEY"}


def _infer_provider(model: str) -> str:
    """按模型名判断该用哪个 Provider 的 SDK。

    model 与 Provider 是绑死的、不是"哪个 API Key 存在就用哪个"能替代的关系——
    claude-* 系列模型只能经 Anthropic 的 Messages API 调用,发去 OpenAI 兼容
    接口只会得到一个牛头不对马嘴的报错。目前接入了三家 Provider,claude-* 走
    Anthropic,glm-* 走智谱,其余(gpt-*/o1-* 等)按现有约定走 OpenAI 兼容协议。
    """
    if model.startswith("claude"):
        return "anthropic"
    if model.startswith("glm"):
        return "zhipu"
    return "openai"


def build_llm_client(model: str | None = None, log_dir: Path | None = None) -> LLMClient:
    """按 model(若给出)或环境变量选一个真实 Provider 并构造 client。

    Args:
        model: 显式指定本次要用的模型名,通常来自 workflow.yaml 里某个节点标注
            的 `model` 字段(见 engine.workflow.Workflow.resolve_stage_models)。
            给出时由 _infer_provider 按模型名决定 Provider——不再看"哪个 API
            Key 恰好存在",对应的 Key 缺失时直接报错,而不是把这个模型名发去
            另一家的 SDK。为 None 时保留旧行为:优先 Anthropic,其次 OpenAI,
            由环境变量里存在哪个 API Key 决定 Provider,模型名退回 NOVEL_MODEL
            环境变量或该 Provider 的默认值。
        log_dir: 非 None 时,给构造出的 client 包一层 LoggingLLMClient,把每次
            chat() 的请求/响应落盘到该目录(见 --log-chats)。
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
        raise RuntimeError(
            "需要设置 ANTHROPIC_API_KEY / OPENAI_API_KEY / ZHIPU_API_KEY 之一才能真实运行本场景;"
            "没有 API Key 时,可运行 `python -m scenarios.novel.offline_demo` "
            "用脚本化回复体验完整流水线(见 scenarios/novel/README.md)。"
        )

    api_key_env = _PROVIDER_API_KEY_ENV[provider]
    api_key = os.environ.get(api_key_env)
    if not api_key:
        raise RuntimeError(
            f"workflow.yaml 里要求使用模型 {model!r},这需要 {provider} 的 SDK,"
            f"但当前环境未设置 {api_key_env}。"
        )
    resolved_model = model or os.environ.get("NOVEL_MODEL", _PROVIDER_DEFAULT_MODEL[provider])

    if provider == "anthropic":
        from llm.providers.anthropic import AnthropicClient

        client: LLMClient = AnthropicClient(
            api_key=api_key,
            model=resolved_model,
            base_url=os.environ.get("ANTHROPIC_API_BASE_URL", "http://localhost:11434/v1"),
            max_tokens=32768,
        )
    elif provider == "zhipu":
        from llm.providers.zhipu import ZhipuClient

        client = ZhipuClient(
            api_key=api_key,
            model=resolved_model,
            base_url=os.environ.get("ZHIPU_API_BASE_URL"),
            max_tokens=32768,
        )
    else:
        from llm.providers.openai import OpenAIClient

        client = OpenAIClient(
            api_key=api_key,
            model=resolved_model,
            base_url=os.environ.get("OPENAI_API_BASE_URL", "http://localhost:11434/v1"),
            max_tokens=32768,
        )

    if log_dir is not None:
        client = LoggingLLMClient(client, log_dir)
    return client


def make_client_factory(log_dir: Path | None = None):
    """按 model 分组、按需惰性构造并复用 LLMClient。

    workflow.yaml 里没有被任何节点标注过 model 的 Stage,收到的 model 是
    None,这些 Stage 共用同一个"默认 client"——与改动前"所有 Stage 共用一个
    client"的行为完全一致。只有显式标注了不同 model 的节点才会各自拿到一个
    新建的 client,不会为同一个 model 反复创建连接。

    Args:
        log_dir: 透传给 build_llm_client,非 None 时每个新建的 client 都会被
            LoggingLLMClient 包一层(见 --log-chats)。
    """
    clients: dict[str | None, LLMClient] = {}

    def factory(_stage_name: str, model: str | None) -> LLMClient:
        if model not in clients:
            clients[model] = build_llm_client(model, log_dir)
        return clients[model]

    return factory


def _print_outline_summary(context: dict[str, Any]) -> None:
    chapters = context.get("story_bible.chapters") or []
    foreshadowing = context.get("story_bible.foreshadowing") or []
    print(f"共 {len(chapters)} 章:")
    for chapter in chapters:
        print(f"  第{chapter.get('index')}章《{chapter.get('title')}》: {chapter.get('beat_summary')}")
    if foreshadowing:
        print("伏笔:")
        for item in foreshadowing:
            print(f"  [{item.get('planted_in_chapter')}] {item.get('description')}")


def _print_chapter_summary(context: dict[str, Any]) -> None:
    chapter_index = context.get("chapter_index")
    chapters = context.get("story_bible.chapters") or []
    chapter = next((c for c in chapters if c.get("index") == chapter_index), None)
    if chapter and chapter.get("draft_summary"):
        print(f"本章摘要:{chapter['draft_summary']}")
    text = context.get("chapter_text", "")
    preview = text[:300] + ("……" if len(text) > 300 else "")
    print(f"本章正文预览(共 {len(text)} 字):\n{preview}")


def make_checkpoint_handler(auto_approve: bool):
    """CLI 版 CheckpointHandler。

    "confirm_outline"/"chapter_pause" 是 outline_loop / chapter_review_loop 各自
    body 里的最后一关:AI critic 通过后才轮到它们(AI 判否时 Loop 已经短路,
    不会走到这里),契约与 AI critic 完全相同:
    {NEEDS_REVISION_KEY: bool, "feedback": str}。needs_revision 为 True 时必须给出
    feedback——Loop 的 continue_when 读到它就重开一轮,从生成节点开始重写,下一轮
    AI 与人工都要再看一次,直到人工放行或跑满 max_iterations(此时会以 Loop 自己的
    名字——如 "outline_loop"——触发下面的兜底分支,而不是这两个 if 分支)。

    Checkpoint 本身只支持同步问答(见 engine.primitives.checkpoint 模块
    docstring),没有"暂停等以后再答"的专属机制;chapter_pause 的 "q" 选项想要的
    "保存进度、下次进程重启再续跑"效果,靠直接抛异常达成——它会被
    engine.workflow.Workflow.run 的通用失败路径包成 WorkflowFailure,和其它节点
    失败一样触发 main() 里的续跑点持久化,效果等价,只是走的是通用失败通道而不是
    Checkpoint 专属通道。
    """

    def handler(request: CheckpointRequest) -> dict[str, Any]:
        print(f"\n=== Checkpoint: {request.name} ===")
        if request.prompt:
            print(request.prompt)
        if request.name == "confirm_outline":
            _print_outline_summary(request.context or {})
            if auto_approve:
                print("[auto] 已自动确认大纲,继续执行。")
                return {NEEDS_REVISION_KEY: False, "feedback": ""}
            answer = input("是否批准当前大纲? [y/N] ").strip().lower()
            if answer == "y":
                return {NEEDS_REVISION_KEY: False, "feedback": ""}
            feedback = input("请输入修改意见(将据此重新生成大纲): ").strip()
            return {NEEDS_REVISION_KEY: True, "feedback": feedback}
        if request.name == "chapter_pause":
            _print_chapter_summary(request.context or {})
            if auto_approve:
                return {NEEDS_REVISION_KEY: False, "feedback": ""}
            answer = input("本章是否通过? [Y]通过并继续 / [n]提出修改意见 / [q]暂停保存进度: ").strip().lower()
            if answer in ("q", "quit"):
                print("[info] 已选择暂停,将保存进度并落地当前产物,可稍后续跑。")
                raise RuntimeError(
                    f"用户在断点 {request.name!r} 选择保存进度并退出,请稍后重新运行本命令续跑。"
                )
            if answer in ("n", "no"):
                feedback = input("请输入修改意见(将据此重新修订本章): ").strip()
                return {NEEDS_REVISION_KEY: True, "feedback": feedback}
            return {NEEDS_REVISION_KEY: False, "feedback": ""}
        print("[warn] Loop 已跑满最大迭代次数仍未通过评审,自动接受最后一版,请事后复核。")
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
    parser.add_argument(
        "--log-chats",
        action="store_true",
        help="记录每次 chat() 的请求/响应到 --output-dir 下的 log 子目录,一次 chat 一个文件",
    )
    args = parser.parse_args()

    brief = load_brief(args.brief)
    log_dir = (args.output_dir / "log") if args.log_chats else None
    workflow = SCENARIO.build_workflow(client_factory=make_client_factory(log_dir))

    state_path = args.state_file or (args.output_dir / DEFAULT_STATE_FILE)
    state_store = JsonFileStateStore(state_path)
    if not state_store.snapshot():
        state_store.load(SCENARIO.empty_state())

    resume = _load_resume_point(state_path)
    if resume is not None:
        print(f"检测到上次未完成的运行,从顶层节点游标 {resume.node_index} 续跑,跳过已成功的前序节点。")

    ctx = RunContext(
        state=state_store,
        checkpoint_handler=make_checkpoint_handler(args.auto_approve),
        hooks=LifecycleHooks(
            before_stage=lambda name, _inputs: print(f"[stage:start] {name}"),
            after_stage=lambda name, _outputs: print(f"[stage:done]  {name}"),
        ),
        resume=resume,
    )

    try:
        outputs = workflow.run(ctx, brief)
    except WorkflowFailure as failure:
        _save_resume_point(state_path, failure.node_index, failure.inputs, failure.node_name)
        print(
            f"流程在节点 {failure.node_name!r}(顶层游标 {failure.node_index})执行失败:"
            f"{failure.__cause__!r}\n"
            f"状态已保存到 {state_path},修复问题后重新运行本命令即可从该节点续跑,"
            f"无需重跑之前已成功的节点。"
        )
        raise

    _clear_resume_point(state_path)
    written = land_output(state_store.snapshot(), args.output_dir)
    print("\n已落地产物:")
    for label, path in written.items():
        print(f"  {label}: {path}")
    print("\nfinal_qa 报告:", outputs.get("qa_report"))


if __name__ == "__main__":
    main()
