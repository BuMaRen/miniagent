"""essay 场景的运行入口。

和 scenarios/example/run.py 不同的地方:这里把"组装 client / StateStore /
RunContext 并跑 workflow"拆成一个独立函数 `run_workflow`,而不是只塞进
`main()`——site/server.py 需要在自己的后台线程里直接调用它(带上自己的
checkpoint_handler/hooks),不走 argparse/CLI 这条路径。`main()` 是 CLI 场景
下对 `run_workflow` 的一层薄封装。

用法(CLI):

    ANTHROPIC_API_KEY=sk-... python -m scenarios.essay.run \\
        --brief path/to/brief.json \\
        --output-dir scenarios/essay/output

brief.json 形如 {"synopsis": "...", "min_words": 6000, "max_words": 12000,
"human_review": true, "generate_cover": false, ...}(完整字段见
scenarios/essay/brief.py)。情节规划/正文编撰/审核/封面四个环节可以分别指定
model/base_url/api_key(为节省成本换用不同 Provider),缺省字段退回
--model/--base-url/--api-key 这组默认配置(见 StageCredentials)。

中途失败时,状态与"从哪个顶层节点续跑"会被保存下来,修好问题后重跑同一条
命令即可接着走。
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from engine.context import CheckpointHandler, CheckpointRequest, LifecycleHooks, ResumePoint, RunContext
from engine.primitives.loop import LoopExceededError
from engine.workflow import WorkflowFailure
from llm.client import LLMClient
from llm.image_client import ImageClient, NotConfiguredImageClient
from llm.logging_client import LoggingLLMClient
from state.backends.json_file import JsonFileStateStore

from scenarios.essay import landing
from scenarios.essay.brief import parse_brief
from scenarios.essay.nodes.planning import PLANNING_CHECKPOINT_LOOP_NAME
from scenarios.essay.schemas.state import BRIEF_PATH, REVIEW_PATH, empty_state
from scenarios.essay.workflow import ClientFactory, build_workflow

DEFAULT_OUTPUT_DIR = Path(__file__).with_name("output")
DEFAULT_STATE_FILE = "essay_state.json"
RESUME_SUFFIX = ".resume.json"

_PROVIDER_DEFAULT_MODEL = {"anthropic": "claude-sonnet-latest", "openai": "gpt-4o", "zhipu": "glm-5.2"}
_PROVIDER_API_KEY_ENV = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "zhipu": "ZHIPU_API_KEY"}
_PROVIDER_BASE_URL_ENV = {
    "anthropic": "ANTHROPIC_API_BASE_URL",
    "openai": "OPENAI_API_BASE_URL",
    "zhipu": "ZHIPU_API_BASE_URL",
}

ApiKeyFor = Callable[[str], "str | None"]

# 场景支持的 client_factory stage_name 集合(前端详解:情节规划/正文编撰/
# 审核各自独立选 model;meta(标题/简介/标签)始终执行,封面是可选环节,
# 两者都同样独立配置,不复用"正文编撰"的)。
STAGE_NAMES = ("planning", "drafting", "review", "meta", "cover")


@dataclass(frozen=True)
class StageCredentials:
    """一个环节要用的模型配置。

    为节省成本,不同环节可能要接不同 Provider/不同便宜程度的模型,因此
    model/base_url/api_key 三者都可以按环节单独覆盖;某个字段留空(None 或
    空字符串)时退回调用方提供的默认配置(见 make_client_factory)。
    """

    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None


class PlanningRejectedError(RuntimeError):
    """情节规划的人工审核连续被驳回超过允许次数,任务终止。

    包一层是为了让调用方(CLI/httpserver)不需要自己判断
    `WorkflowFailure.__cause__` 是不是恰好来自 planning_checkpoint_loop——
    这是需求文档明确要求"前端标红显示"的一种特殊终止,和其它原因导致的失败
    (网络错误、契约解析失败……)语义不同。
    """


# ---------------------------------------------------------------------------
# 续跑点(照抄 scenarios/example/run.py 的 sidecar 机制)
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


def _infer_provider(model: str, base_url: str | None = None) -> str:
    """按 base_url/模型名判断该用哪家 SDK。

    base_url 指向 OpenRouter 时优先级最高,直接归到 openai——OpenRouter 的
    /chat/completions 端点就是 OpenAI 协议的直接兼容(官方文档原话是"OpenAI
    SDK 可以直接当 drop-in replacement 指过去"),不需要单独一个 Provider
    实现,复用 OpenAIClient 即可。这里不能再按 model 前缀猜:OpenRouter 上的
    模型名习惯带 vendor 前缀(如 "anthropic/claude-sonnet-4.5"),但就算用户
    填的是裸的 "claude-*",只要 base_url 摆明是 OpenRouter,也必须走
    OpenAIClient——之前踩过坑:model 叫 claude-* 时被判成 anthropic,顺着
    AnthropicClient 把请求发去 OpenRouter,命中的是它未文档化的 Anthropic
    协议模拟层,实测会在工具调用输出里泄漏它内部模拟用的 XML 标签
    (<invoke>/<parameter>),导致结构化输出被截断/夹带垃圾字符。

    没有 base_url 或者 base_url 不是 OpenRouter 时,退回原来的按模型名前缀
    猜:claude-* 走 Anthropic,glm-* 走智谱,其余走 OpenAI 兼容协议。
    """
    if base_url and "openrouter.ai" in base_url:
        return "openai"
    if model.startswith("claude"):
        return "anthropic"
    if model.startswith("glm"):
        return "zhipu"
    return "openai"


def env_api_key_for(provider: str) -> str | None:
    """默认的 api_key_for 实现:按环境变量取(CLI 场景用)。"""
    return os.environ.get(_PROVIDER_API_KEY_ENV[provider])


def build_llm_client(
    model: str | None,
    api_key_for: ApiKeyFor = env_api_key_for,
    base_url: str | None = None,
    log_dir: Path | None = None,
) -> LLMClient:
    """按 model(若给出)或 api_key_for 里存在哪个 Provider 的 key 决定用哪家 SDK。

    Args:
        model: 本次要用的模型名;为 None 时按 api_key_for 里第一个有值的
            Provider 决定,模型名退回该 Provider 的默认值。
        api_key_for: (provider) -> api_key,缺失该 Provider 的 key 时返回 None。
        base_url: 非 None 时覆盖该 Provider 的默认 base_url。
        log_dir: 非 None 时包一层 LoggingLLMClient,把每次 chat() 落盘。
    """
    # base_url 指向 OpenRouter 时优先级最高:哪怕 model 是 None(CLI 靠环境
    # 变量探测 Provider 的场景),也不该退回"看哪个 Provider 的 env key 存在"
    # 这条完全不看 base_url 的路——那样选出来的 Provider 可能和 base_url 对
    # 不上(见 _infer_provider 的说明)。
    if base_url and "openrouter.ai" in base_url:
        provider = "openai"
    elif model is not None:
        provider = _infer_provider(model, base_url)
    else:
        provider = next((p for p in _PROVIDER_API_KEY_ENV if api_key_for(p)), None)
        if provider is None:
            raise RuntimeError("需要提供至少一个 Provider(anthropic/openai/zhipu)的 API Key 才能运行本场景。")

    api_key = api_key_for(provider)
    if not api_key:
        raise RuntimeError(f"使用模型 {model!r} 需要 {provider} 的 API Key,但未提供。")
    resolved_model = model or _PROVIDER_DEFAULT_MODEL[provider]
    resolved_base_url = base_url or os.environ.get(_PROVIDER_BASE_URL_ENV[provider])

    if provider == "anthropic":
        from llm.providers.anthropic import AnthropicClient

        client: LLMClient = AnthropicClient(
            api_key=api_key, model=resolved_model, base_url=resolved_base_url, max_tokens=16384
        )
    elif provider == "zhipu":
        from llm.providers.zhipu import ZhipuClient

        client = ZhipuClient(api_key=api_key, model=resolved_model, base_url=resolved_base_url, max_tokens=16384)
    else:
        from llm.providers.openai import OpenAIClient

        client = OpenAIClient(api_key=api_key, model=resolved_model, base_url=resolved_base_url, max_tokens=16384)

    if log_dir is not None:
        client = LoggingLLMClient(client, log_dir)
    return client


def make_client_factory(
    default: StageCredentials = StageCredentials(),
    overrides: dict[str, StageCredentials] | None = None,
    log_dir: Path | None = None,
) -> ClientFactory:
    """按 stage_name 查 overrides 拿到该环节的模型配置,缺的字段退回 default,
    按需惰性构造并复用 LLMClient。

    对应"前端详解"里情节规划/正文编撰/审核/封面各自独立、可选的模型配置——
    每个环节可以为了省钱换一个更便宜的 Provider/模型,不填的字段(model/
    base_url/api_key)就用 default 里对应的值兜底。`default` 留空(全 None)
    时等价于旧行为:模型名由调用方逐个传,API Key 退回环境变量
    (env_api_key_for),兼容 CLI 不指定任何凭据、纯靠环境变量跑的用法。
    """
    overrides = overrides or {}
    clients: dict[tuple[str | None, str | None, str | None], LLMClient] = {}

    def factory(stage_name: str, model_override: str | None = None) -> LLMClient:
        cfg = overrides.get(stage_name) or StageCredentials()
        model = model_override or cfg.model or default.model
        base_url = cfg.base_url or default.base_url
        api_key = cfg.api_key or default.api_key

        cache_key = (model, base_url, api_key)
        if cache_key not in clients:
            clients[cache_key] = build_llm_client(
                model,
                api_key_for=lambda provider, _key=api_key: _key or env_api_key_for(provider),
                base_url=base_url,
                log_dir=log_dir,
            )
        return clients[cache_key]

    return factory


# ---------------------------------------------------------------------------
# 可复用的运行函数(CLI 与 httpserver 共用)
# ---------------------------------------------------------------------------


def run_workflow(
    brief: dict[str, Any],
    *,
    output_dir: Path,
    state_path: Path,
    default_credentials: StageCredentials = StageCredentials(),
    stage_credentials: dict[str, StageCredentials] | None = None,
    image_client: ImageClient | None = None,
    checkpoint_handler: CheckpointHandler | None = None,
    hooks: LifecycleHooks | None = None,
    log_dir: Path | None = None,
    fresh: bool = False,
) -> dict[str, Any]:
    """校验 brief、拼装 workflow、跑完整个流程,返回 landing.write() 的结果。

    Raises:
        ValueError: brief 不合法(见 scenarios.essay.brief.parse_brief)。
        PlanningRejectedError: 情节规划人工审核连续被驳回超过允许次数。
        WorkflowFailure: 其它未预期的失败(网络错误、契约解析失败……),状态与
            续跑点已保存,修复后用同样的 state_path 重跑即可续上。
    """
    brief = parse_brief(brief)  # 先校验,后组装——设定写错时立刻报错。

    client_factory = make_client_factory(default_credentials, stage_credentials, log_dir)
    workflow = build_workflow(
        client_factory=client_factory,
        image_client=image_client or NotConfiguredImageClient(),
        human_review=brief["human_review"],
        generate_cover=brief["generate_cover"],
    )

    state_store = JsonFileStateStore(state_path)
    if fresh:
        state_store.load(empty_state())
        _clear_resume_point(state_path)
    elif not state_store.snapshot():
        state_store.load(empty_state())

    # 没有专门的"读 brief"节点:brief 已经是校验过的结构化数据,直接写入
    # 初始状态,各节点按需通过 reads=[BRIEF_PATH] 读取。
    state_store.patch(BRIEF_PATH, brief)

    resume = _load_resume_point(state_path)
    ctx = RunContext(state=state_store, checkpoint_handler=checkpoint_handler, hooks=hooks, resume=resume)

    try:
        workflow.run(ctx, {})
    except WorkflowFailure as failure:
        _save_resume_point(state_path, failure.node_index, failure.inputs, failure.node_name)
        if isinstance(failure.__cause__, LoopExceededError) and PLANNING_CHECKPOINT_LOOP_NAME in str(
            failure.__cause__
        ):
            raise PlanningRejectedError(
                "情节规划连续被驳回超过允许次数,任务已终止;请修改简介后重新开始(不能直接续跑)。"
            ) from failure
        raise

    _clear_resume_point(state_path)
    return landing.write(state_store.snapshot(), output_dir)


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------


def _print_after_stage(name: str, outputs: dict[str, Any]) -> None:
    print(f"[stage:done]  {name}")
    if name == "review":
        # 打出审核发现的问题(字数是否达标、AI 修正错别字后的驳回结论),不然
        # CLI 只能看到一行空壳的 "[stage:done] review",不知道这一轮通过没有。
        review = outputs.get(REVIEW_PATH) or {}
        if review.get("rejected"):
            print(f"[review] 打回: {review.get('feedback', '')}")
        else:
            print("[review] 通过")


def cli_checkpoint_handler(request: CheckpointRequest) -> dict[str, Any]:
    print(f"\n[checkpoint:{request.name}] {request.prompt or ''}")
    if request.context:
        print(json.dumps(request.context, ensure_ascii=False, indent=2))
    approved = input("是否通过?(y/n): ").strip().lower() in ("y", "yes", "是")
    feedback = "" if approved else input("驳回理由: ").strip()
    return {"approved": approved, "feedback": feedback}


def main() -> None:
    parser = argparse.ArgumentParser(description="根据简介生成并审核一篇短篇小说")
    parser.add_argument("--brief", type=Path, required=True, help="brief JSON 文件路径")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="产物落地目录")
    parser.add_argument("--state-file", type=Path, default=None, help="状态文件路径(默认写到 --output-dir 下)")

    parser.add_argument("--model", default=None, help="默认模型名(环节没单独指定时使用;留空按环境变量探测 Provider)")
    parser.add_argument("--base-url", default=None, help="默认 base_url")
    parser.add_argument("--api-key", default=None, help="默认 API Key(留空则读取对应 Provider 的环境变量)")
    for stage in STAGE_NAMES:
        parser.add_argument(f"--{stage}-model", default=None, help=f"{stage} 环节使用的模型名(覆盖默认)")
        parser.add_argument(f"--{stage}-base-url", default=None, help=f"{stage} 环节使用的 base_url(覆盖默认)")
        parser.add_argument(f"--{stage}-api-key", default=None, help=f"{stage} 环节使用的 API Key(覆盖默认)")

    parser.add_argument("--log-chats", action="store_true", help="把每次 chat() 的请求/响应落盘")
    parser.add_argument("--fresh", action="store_true", help="丢弃已有状态,从零重新跑一遍")
    args = parser.parse_args()

    if not args.brief.is_file():
        raise SystemExit(f"brief 文件不存在: {args.brief}")
    with args.brief.open("r", encoding="utf-8") as f:
        brief_raw = json.load(f)

    output_dir: Path = args.output_dir
    log_dir = (output_dir / "log") if args.log_chats else None
    state_path = args.state_file or (output_dir / DEFAULT_STATE_FILE)
    human_review = bool(brief_raw.get("human_review", False))

    default_credentials = StageCredentials(model=args.model, base_url=args.base_url, api_key=args.api_key)
    stage_credentials = {
        stage: StageCredentials(
            model=getattr(args, f"{stage}_model"),
            base_url=getattr(args, f"{stage}_base_url"),
            api_key=getattr(args, f"{stage}_api_key"),
        )
        for stage in STAGE_NAMES
    }

    try:
        result = run_workflow(
            brief_raw,
            output_dir=output_dir,
            state_path=state_path,
            default_credentials=default_credentials,
            stage_credentials=stage_credentials,
            checkpoint_handler=cli_checkpoint_handler if human_review else None,
            hooks=LifecycleHooks(
                before_stage=lambda name, _inputs: print(f"[stage:start] {name}"),
                after_stage=_print_after_stage,
                before_loop_iteration=lambda name, i: print(f"[loop] {name} 第 {i + 1} 轮"),
                on_checkpoint=lambda name: print(f"[checkpoint] {name}"),
            ),
            log_dir=log_dir,
            fresh=args.fresh,
        )
    except PlanningRejectedError as err:
        print(f"\n{err}")
        raise SystemExit(1) from err
    except WorkflowFailure as failure:
        print(
            f"\n流程在节点 {failure.node_name!r}(顶层游标 {failure.node_index})执行失败:"
            f"{failure.__cause__!r}\n状态已保存到 {state_path},修复后重跑本命令即可从该节点续跑。"
        )
        raise

    print(f"\n已落地产物: {result['manuscript_path']}")
    print(f"全篇字数: {result['total_words']}")
    if result["needs_manual_review"]:
        print("注意:改稿循环跑满重试次数仍未通过审核,建议人工复核。")
    if result.get("cover_image", {}).get("url"):
        print(f"封面: {result['cover_image']['url']}")


if __name__ == "__main__":
    main()
