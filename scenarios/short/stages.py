"""把 prompt + ToolSet 挂到 Agent 上,组装成本场景的各个节点。

三条贯穿全模块的约定:

1. **prompt 一律来自 prompts.py**,本模块不写任何 prompt 文本;prompts.py 里也
   不写任何题材内容(那些在用户的 brief.yaml 里)。这就是需求里"用户输入的
   prompt 与流程使用的 prompt 要分开"在代码上的落点。

2. **模型只产出它真正创作的那部分,拼装交给代码。** 与 scenarios/novel 不同,
   这里的撰写节点不要求模型"原样回显整个 sections 数组":它只返回本节的
   text 与 summary,由 executor 读出当前数组、替换掉这一节、把整份新数组作为
   Stage 的输出交给声明式的 writes 写回。省下的不只是 token —— 让模型抄一遍
   前面几节的正文,本身就是丢字、改字、串味的主要来源。
   于是每个 LLM 节点有两份 schema:给 Agent 的(模型该吐什么)和给 Stage 的
   (写回状态的是什么),职责不同,不该合并。

3. **能算的不交给模型判断。** 字数、句长分布、单句成段比例、套话密度、大纲的
   编号与预算合计,全部由 toolsets/ 里的确定性函数先算一遍;算出的问题无条件
   并进 Critic 的判定(见 _merge_verdict),模型只负责它算不出来的部分:错别字、
   语病、逻辑、人物、爽点是否立住。这是"不能有语病/错别字/AI 痕迹"这条硬要求
   在没有人工复核时唯一靠得住的兜底。
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from agent.agent import Agent
from agent.memory import ConversationMemory
from engine.context import RunContext
from engine.stage import Stage
from llm.client import LLMClient
from state.schema import StateSchema
from tools.registry import ToolRegistry

from scenarios.short import prompts
from scenarios.short.brief import parse_brief
from scenarios.short.state_schema import CHARACTER, PAYOFF, SECTION
from scenarios.short.toolsets.structure import outline_problems, section_length_problem
from scenarios.short.toolsets.style import (
    STYLE_TOOLSET,
    count_chinese_characters,
    style_metrics,
    style_violations,
)

logger = logging.getLogger(__name__)

# 由调用方(run.py)提供:按 (节点名, 生效 model) 给出一个 LLMClient。
# 语义与 scenarios/novel 完全一致,见 engine.workflow.Workflow.resolve_stage_models。
ClientFactory = Callable[[str, str | None], LLMClient]

_DEFAULT_MAX_STEPS = 6

# 评审类节点的判定字段名。极性朝着"还要再改一轮"为真 —— workflow.yaml 里的
# continue_when 是一条裸状态路径,引擎只取真假,没有取反的余地(见
# engine/primitives/loop.py)。
NEEDS_REVISION_KEY = "needs_revision"

# Loop / ForEach 的游标路径,必须与 workflow.yaml 里各节点的 name 对得上。
OUTLINE_LOOP_LAST_PATH = "_loop.outline_loop.last"
SECTION_REVIEW_LOOP_LAST_PATH = "_loop.section_review_loop.last"
SECTION_ITEM_PATH = "_foreach.section_loop.item"

# 状态路径
BRIEF_PATH = "short_story.brief"
META_PATH = "short_story.meta"
CHARACTERS_PATH = "short_story.characters"
PAYOFFS_PATH = "short_story.payoffs"
SECTIONS_PATH = "short_story.sections"

# 大纲阶段只产出 SECTION 的"计划字段",正文相关字段(text/summary/word_count/
# status)由代码填占位值 —— 从 SECTION 投影出来而不是另抄一份,免得两边各改各的。
_OUTLINE_SECTION = {k: SECTION[k] for k in ("index", "title", "beat_summary", "payoff_note", "word_budget")}


# ---------------------------------------------------------------------------
# Agent 组装
# ---------------------------------------------------------------------------


def _make_agent(
    client: LLMClient,
    system_prompt: str,
    toolsets: tuple = (),
    output_schema: StateSchema | None = None,
) -> Agent:
    registry = ToolRegistry()
    agent = Agent(
        client=client,
        memory=ConversationMemory(system_prompt=system_prompt),
        registry=registry,
        max_steps=_DEFAULT_MAX_STEPS,
        output_schema=output_schema,
    )
    for toolset in toolsets:
        agent.load_toolset(toolset)
    return agent


def _ask(agent: Agent, ctx: RunContext, payload: dict[str, Any]) -> dict[str, Any]:
    """把 payload 交给 Agent 跑一次,并保证每次都从干净的对话记忆开始。

    节点在 build_node_registry 时只造一次,而 ForEach 会让同一个 Agent 实例被每
    一节复用。不清空记忆的话,第 N 节的请求里会拖着前 N-1 节的全部正文与评审
    意见:开销随节数累积是小事,真正的麻烦是模型会顺着自己上一节的句式继续写
    ——那正是我们要防的"AI 痕迹"。跨节需要的连贯性一律走 State(前情摘要、上
    一节结尾原文、骨架设定),不靠对话历史。
    """
    agent.memory.messages = []
    return agent.run(ctx, payload)


def _merge_verdict(verdict: dict[str, Any], auto_problems: list[str]) -> dict[str, Any]:
    """把"确定性体检发现的问题"与"LLM Critic 的意见"合成一份判定。

    确定性问题一票否决:只要有一条,不管模型说什么都判否,并把问题原文放进
    feedback ——下一轮的撰写/精修节点会照着它改。模型的意见附在后面,不丢弃。
    """
    llm_feedback = str(verdict.get("feedback") or "").strip()
    if auto_problems:
        parts = ["【确定性体检(必须改)】"] + [f"- {p}" for p in auto_problems]
        if llm_feedback:
            parts += ["【审校意见】", llm_feedback]
        return {NEEDS_REVISION_KEY: True, "feedback": "\n".join(parts)}
    return {NEEDS_REVISION_KEY: bool(verdict.get(NEEDS_REVISION_KEY)), "feedback": llm_feedback}


CRITIC_OUTPUT_SCHEMA = StateSchema("critic_output", {NEEDS_REVISION_KEY: bool, "feedback": str})


# ---------------------------------------------------------------------------
# 状态读写小工具
# ---------------------------------------------------------------------------


def _feedback_from(state: dict[str, Any], cursor_path: str) -> str:
    """从 Loop 游标里取上一轮的评审意见;首轮(游标为空)返回空串。"""
    return str(((state.get(cursor_path) or {}).get("feedback") or "")).strip()


def _replace_section(sections: list[dict], index: Any, **updates: Any) -> list[dict]:
    """返回一份新的 sections:把 index 对应的那一节按 updates 更新,其余原样。"""
    return [{**s, **updates} if s.get("index") == index else s for s in sections]


def _previous_digest(sections: list[dict], current_index: Any) -> list[dict]:
    """前情提要:此前各节的摘要,不含正文。

    正文只回传上一节的结尾(见 _tail),其余用摘要 —— 短篇总共不到一万字,
    整篇塞进去当然塞得下,但每节都塞一遍会让上下文与费用随节数平方增长,
    而且模型更容易顺着旧句式复读。
    """
    return [
        {"index": s.get("index"), "title": s.get("title"), "summary": s.get("summary", "")}
        for s in sections
        if isinstance(s.get("index"), int) and isinstance(current_index, int) and s["index"] < current_index
    ]


def _tail(sections: list[dict], current_index: Any, chars: int = 400) -> str:
    """上一节结尾的原文片段,用来接住语气与悬念。"""
    if not isinstance(current_index, int):
        return ""
    previous = next((s for s in sections if s.get("index") == current_index - 1), None)
    text = (previous or {}).get("text") or ""
    return text[-chars:]


def _section_text(sections: list[dict], index: Any) -> str:
    """从 sections 状态里取当前节的最新正文。

    section_polish/section_critic 现在被包进 section_review_loop:Loop 每轮都
    从同一份 inputs 重新开始(见 engine/primitives/loop.py 的说明),通道①的
    "text" 只保真同一轮内紧邻的两个节点,跨轮次会被重置回循环最初收到的那份
    inputs,看不到上一轮精修的结果。只有 ctx.state 是跨轮次可靠的,所以这两个
    节点都必须从这里读正文,不能再依赖通道①。
    """
    section = next((s for s in sections if s.get("index") == index), None)
    return str((section or {}).get("text") or "")


def _story_context(state: dict[str, Any]) -> dict[str, Any]:
    """骨架 + 角色 + 爽点设计 —— 每个写作/审校节点都要看的那份全局事实。"""
    return {
        "meta": state.get(META_PATH) or {},
        "characters": state.get(CHARACTERS_PATH) or [],
        "payoffs": state.get(PAYOFFS_PATH) or [],
    }


# ---------------------------------------------------------------------------
# 1. 输入解析 —— 纯函数,不需要 LLM。
# ---------------------------------------------------------------------------


def input_parsing_executor(ctx: RunContext, inputs: dict[str, Any]) -> dict[str, Any]:
    """校验用户设定并落进 State。

    inputs 就是 run.py 读进来的 brief.yaml。这里再调一次 parse_brief 而不是信任
    宿主:parse_brief 是幂等的(补过默认值的 brief 再解析一次结果不变),多跑
    一次的代价是零,换来的是"不管谁来驱动这个 Workflow,short_story.brief 都
    必然是一份合法的完整设定"。
    """
    brief = parse_brief({k: v for k, v in inputs.items() if k != "state"})
    return {BRIEF_PATH: brief}


def build_input_parsing_stage() -> Stage:
    return Stage(name="input_parsing", executor=input_parsing_executor, writes=[BRIEF_PATH])


# ---------------------------------------------------------------------------
# 2. 故事骨架设计
# ---------------------------------------------------------------------------

STORY_DESIGN_AGENT_SCHEMA = StateSchema(
    "story_design_agent_output",
    {
        "title": str,
        "logline": str,
        "one_line_hook": str,
        "core_conflict": str,
        "characters": [CHARACTER],
    },
)

STORY_DESIGN_OUTPUT_SCHEMA = StateSchema(
    "story_design_output", {META_PATH: {"title": str, "logline": str, "one_line_hook": str, "core_conflict": str}, CHARACTERS_PATH: [CHARACTER]}
)


def build_story_design_stage(client: LLMClient) -> Stage:
    agent = _make_agent(client, prompts.STORY_DESIGN, output_schema=STORY_DESIGN_AGENT_SCHEMA)

    def executor(ctx: RunContext, inputs: dict[str, Any]) -> dict[str, Any]:
        state = inputs.get("state", {})
        out = _ask(agent, ctx, {prompts.KEY_BRIEF: state.get(BRIEF_PATH) or {}})
        return {
            META_PATH: {
                "title": str(out.get("title") or ""),
                "logline": str(out.get("logline") or ""),
                "one_line_hook": str(out.get("one_line_hook") or ""),
                "core_conflict": str(out.get("core_conflict") or ""),
            },
            CHARACTERS_PATH: out.get("characters") or [],
        }

    return Stage(
        name="story_design",
        executor=executor,
        reads=[BRIEF_PATH],
        writes=[META_PATH, CHARACTERS_PATH],
        output_schema=STORY_DESIGN_OUTPUT_SCHEMA,
    )


# ---------------------------------------------------------------------------
# 3. 分节大纲 + 大纲评审(outline_loop 的 body)
#
# 生成与修订是同一个节点:游标为空就是生成,游标里带着上一轮的评审意见就是修订。
# ---------------------------------------------------------------------------

OUTLINE_AGENT_SCHEMA = StateSchema(
    "outline_agent_output", {"sections": [_OUTLINE_SECTION], "payoffs": [PAYOFF]}
)

OUTLINE_OUTPUT_SCHEMA = StateSchema(
    "outline_output", {SECTIONS_PATH: [SECTION], PAYOFFS_PATH: [PAYOFF]}
)


def _plan_section(raw: dict[str, Any]) -> dict[str, Any]:
    """把大纲条目补齐成一个完整的 SECTION(正文字段留空,等撰写阶段填)。"""
    return {
        "index": int(raw.get("index") or 0),
        "title": str(raw.get("title") or ""),
        "beat_summary": str(raw.get("beat_summary") or ""),
        "payoff_note": str(raw.get("payoff_note") or ""),
        "word_budget": int(raw.get("word_budget") or 0),
        "text": "",
        "summary": "",
        "word_count": 0,
        "status": "planned",
    }


def build_outline_generation_stage(client: LLMClient) -> Stage:
    agent = _make_agent(client, prompts.OUTLINE, output_schema=OUTLINE_AGENT_SCHEMA)

    def executor(ctx: RunContext, inputs: dict[str, Any]) -> dict[str, Any]:
        state = inputs.get("state", {})
        out = _ask(
            agent,
            ctx,
            {
                prompts.KEY_BRIEF: state.get(BRIEF_PATH) or {},
                prompts.KEY_STORY: _story_context(state),
                prompts.KEY_FEEDBACK: _feedback_from(state, OUTLINE_LOOP_LAST_PATH),
            },
        )
        return {
            SECTIONS_PATH: [_plan_section(s) for s in out.get("sections") or []],
            PAYOFFS_PATH: list(out.get("payoffs") or []),
        }

    return Stage(
        name="outline_generation",
        executor=executor,
        reads=[OUTLINE_LOOP_LAST_PATH, BRIEF_PATH, META_PATH, CHARACTERS_PATH, PAYOFFS_PATH],
        writes=[SECTIONS_PATH, PAYOFFS_PATH],
        output_schema=OUTLINE_OUTPUT_SCHEMA,
    )


def build_outline_critic_stage(client: LLMClient) -> Stage:
    agent = _make_agent(client, prompts.OUTLINE_CRITIC, output_schema=CRITIC_OUTPUT_SCHEMA)

    def executor(ctx: RunContext, inputs: dict[str, Any]) -> dict[str, Any]:
        state = inputs.get("state", {})
        brief = state.get(BRIEF_PATH) or {}
        sections = state.get(SECTIONS_PATH) or []
        payoffs = state.get(PAYOFFS_PATH) or []
        # 先算后问:确定性问题连同大纲一起交给模型,免得它把注意力浪费在数数上。
        auto_problems = outline_problems(sections, payoffs, brief.get("target_word_count") or [0, 0])
        verdict = _ask(
            agent,
            ctx,
            {
                prompts.KEY_OUTLINE: {"sections": sections, "payoffs": payoffs},
                prompts.KEY_BRIEF: brief,
                prompts.KEY_STORY: _story_context(state),
                prompts.KEY_AUTO_PROBLEMS: auto_problems,
            },
        )
        return _merge_verdict(verdict, auto_problems)

    return Stage(
        name="outline_critic",
        executor=executor,
        reads=[BRIEF_PATH, META_PATH, CHARACTERS_PATH, SECTIONS_PATH, PAYOFFS_PATH],
        output_schema=CRITIC_OUTPUT_SCHEMA,
    )


# ---------------------------------------------------------------------------
# 4. 逐节撰写 / 语言精修 / 审校
#
# 撰写只管情节与爽点,精修只管语言 —— 两件事要的注意力不同,合成一个节点时
# 模型总会顾此失彼(让它一边编爆点一边数句长,两头都糊)。
#
# workflow.yaml 里 foreach 的 body 是 sequence([section_drafting] 保底拿到一份
# 初稿)接一个 section_review_loop(body=[section_polish, section_critic]):
# 精修在前、审校在后,判否就从 body[0] 重开一轮精修,判过则这一节到此为止。
# 撰写只跑这一次、不进循环 —— 情节与爽点定死之后不再重赌;循环只反复"精修 ->
# 审校",成本随质量需要而变,而不是像撰写那样一次性摊死。
# ---------------------------------------------------------------------------

SECTION_DRAFTING_AGENT_SCHEMA = StateSchema("section_drafting_agent_output", {"text": str, "summary": str})
SECTION_POLISH_AGENT_SCHEMA = StateSchema("section_polish_agent_output", {"text": str, "revision_notes": str})

# 两个写作节点对 Stage 的输出契约是同一份:整份 sections(交给 writes 写回)+
# 本节 index 与正文。text 这个通道①字段只在同一轮内紧邻的下一个节点有用
# (调试、日志);跨 Loop 轮次的正文一律靠 _section_text() 从 state 里读,见
# 该函数的说明。
SECTION_WRITE_OUTPUT_SCHEMA = StateSchema(
    "section_write_output", {SECTIONS_PATH: [SECTION], "section_index": int, "text": str}
)


def _current_section(state: dict[str, Any]) -> dict[str, Any]:
    """ForEach 发布在游标上的"本节大纲"。"""
    return state.get(SECTION_ITEM_PATH) or {}


def build_section_drafting_stage(client: LLMClient) -> Stage:
    agent = _make_agent(client, prompts.SECTION_DRAFTING, output_schema=SECTION_DRAFTING_AGENT_SCHEMA)

    def executor(ctx: RunContext, inputs: dict[str, Any]) -> dict[str, Any]:
        state = inputs.get("state", {})
        sections = state.get(SECTIONS_PATH) or []
        current = _current_section(state)
        index = current.get("index")
        following = next((s for s in sections if s.get("index") == (index or 0) + 1), None)

        out = _ask(
            agent,
            ctx,
            {
                prompts.KEY_SECTION: current,
                prompts.KEY_BUDGET: current.get("word_budget"),
                prompts.KEY_NEXT_SECTION: {
                    "index": (following or {}).get("index"),
                    "beat_summary": (following or {}).get("beat_summary", ""),
                } if following else {},
                prompts.KEY_PREVIOUS: _previous_digest(sections, index),
                prompts.KEY_LAST_TEXT: _tail(sections, index),
                prompts.KEY_STORY: _story_context(state),
                prompts.KEY_BRIEF: state.get(BRIEF_PATH) or {},
                prompts.KEY_FEEDBACK: _feedback_from(state, SECTION_REVIEW_LOOP_LAST_PATH),
            },
        )
        text = str(out.get("text") or "")
        if not text:
            # 不抛异常:空正文会被本轮的确定性字数体检判否,Loop 自己会重写一遍,
            # 比让整条流水线失败、要人来重跑划算。
            logger.warning("section_drafting: 第 %s 节没有拿到正文,交给审校判否后重写", index)
        return {
            SECTIONS_PATH: _replace_section(
                sections,
                index,
                text=text,
                summary=str(out.get("summary") or ""),
                word_count=count_chinese_characters(text),
                status="drafted",
            ),
            "section_index": index if isinstance(index, int) else 0,
            "text": text,
        }

    return Stage(
        name="section_drafting",
        executor=executor,
        reads=[
            SECTION_REVIEW_LOOP_LAST_PATH,
            SECTION_ITEM_PATH,
            BRIEF_PATH,
            META_PATH,
            CHARACTERS_PATH,
            PAYOFFS_PATH,
            SECTIONS_PATH,
        ],
        writes=[SECTIONS_PATH],
        output_schema=SECTION_WRITE_OUTPUT_SCHEMA,
    )


def build_section_polish_stage(client: LLMClient) -> Stage:
    agent = _make_agent(
        client,
        prompts.SECTION_POLISH,
        toolsets=(STYLE_TOOLSET,),
        output_schema=SECTION_POLISH_AGENT_SCHEMA,
    )

    def executor(ctx: RunContext, inputs: dict[str, Any]) -> dict[str, Any]:
        state = inputs.get("state", {})
        sections = state.get(SECTIONS_PATH) or []
        current = _current_section(state)
        index = current.get("index")
        text = _section_text(sections, index)

        # 字数不达标(尤其是低于下限——这是硬要求,见 section_length_problem)
        # 与文风越界一律并进整改清单,让这一次精修顺手把长度拉回预算。
        problems = style_violations(text)
        length_problem = section_length_problem(
            count_chinese_characters(text), int(current.get("word_budget") or 0)
        )
        if length_problem:
            problems = [length_problem, *problems]

        # 每节至少跑一趟,即便确定性体检一条都没报:语病、错别字、标点误用是
        # 程序看不见的,而它们恰恰是本场景唯一不肯让步的红线。本节点被包在
        # section_review_loop 里(见 workflow.yaml),审校判否时会带着具体意见
        # 再跑一轮——KEY_FEEDBACK 非空就是上一轮被驳回的理由。
        out = _ask(
            agent,
            ctx,
            {
                prompts.KEY_SECTION: current,
                prompts.KEY_TEXT: text,
                prompts.KEY_BUDGET: current.get("word_budget"),
                prompts.KEY_BRIEF: state.get(BRIEF_PATH) or {},
                prompts.KEY_METRICS: style_metrics(text),
                prompts.KEY_AUTO_PROBLEMS: problems,
                prompts.KEY_FEEDBACK: _feedback_from(state, SECTION_REVIEW_LOOP_LAST_PATH),
            },
        )
        polished_raw = str(out.get("text") or "").strip()
        original_count = count_chinese_characters(text)
        polished_count = count_chinese_characters(polished_raw)
        # 精修偶尔会在模型把输出配额大量耗在内部推理上时"腰斩"——JSON 本身合法,
        # 但 text 字段只剩开头半句话。这种退化结果比不精修还坏(整节已经成立的
        # 情节被冲掉),所以字数骤降时弃用这次精修、保留精修前的正文,状态也如实
        # 标回 drafted,而不是谎称已精修。
        degraded = bool(polished_raw) and original_count >= 200 and polished_count < original_count * 0.5
        if degraded:
            logger.warning(
                "section_polish: 第 %s 节精修结果字数从 %d 骤降到 %d,判定为退化输出,保留精修前正文",
                index,
                original_count,
                polished_count,
            )
        polished = text if degraded else (polished_raw or text)
        return {
            SECTIONS_PATH: _replace_section(
                sections,
                index,
                text=polished,
                word_count=count_chinese_characters(polished),
                status="drafted" if degraded else "polished",
            ),
            "section_index": index if isinstance(index, int) else 0,
            "text": polished,
        }

    return Stage(
        name="section_polish",
        executor=executor,
        reads=[SECTION_REVIEW_LOOP_LAST_PATH, SECTION_ITEM_PATH, BRIEF_PATH, SECTIONS_PATH],
        writes=[SECTIONS_PATH],
        output_schema=SECTION_WRITE_OUTPUT_SCHEMA,
    )


def build_section_critic_stage(client: LLMClient) -> Stage:
    agent = _make_agent(
        client, prompts.SECTION_CRITIC, toolsets=(STYLE_TOOLSET,), output_schema=CRITIC_OUTPUT_SCHEMA
    )

    def executor(ctx: RunContext, inputs: dict[str, Any]) -> dict[str, Any]:
        state = inputs.get("state", {})
        sections = state.get(SECTIONS_PATH) or []
        current = _current_section(state)
        index = current.get("index")
        text = _section_text(sections, index)

        auto_problems = style_violations(text)
        length_problem = section_length_problem(
            count_chinese_characters(text), int(current.get("word_budget") or 0)
        )
        if length_problem:
            auto_problems = [length_problem, *auto_problems]

        verdict = _ask(
            agent,
            ctx,
            {
                prompts.KEY_SECTION: current,
                prompts.KEY_TEXT: text,
                prompts.KEY_PREVIOUS: _previous_digest(sections, index),
                prompts.KEY_STORY: _story_context(state),
                prompts.KEY_BRIEF: state.get(BRIEF_PATH) or {},
                prompts.KEY_METRICS: style_metrics(text),
                prompts.KEY_AUTO_PROBLEMS: auto_problems,
            },
        )
        return _merge_verdict(verdict, auto_problems)

    return Stage(
        name="section_critic",
        executor=executor,
        reads=[
            SECTION_ITEM_PATH,
            BRIEF_PATH,
            META_PATH,
            CHARACTERS_PATH,
            PAYOFFS_PATH,
            SECTIONS_PATH,
        ],
        output_schema=CRITIC_OUTPUT_SCHEMA,
    )


# ---------------------------------------------------------------------------
# 5. 终检 —— 纯函数,不需要 LLM。
#
# 没有人工复核环节,所以这一步的价值不是"再改一遍",而是"如实交代成品的成色":
# 总字数、各节字数、还残留哪些文风越界项。它写进 qa_report,由 landing.py 落盘,
# 谁拿到成品都能一眼看出哪几节需要人再看一下。
# ---------------------------------------------------------------------------


def final_qa_executor(ctx: RunContext, inputs: dict[str, Any]) -> dict[str, Any]:
    state = inputs.get("state", {})
    sections = state.get(SECTIONS_PATH) or []
    meta = state.get(META_PATH) or {}
    brief = state.get(BRIEF_PATH) or {}

    updated: list[dict[str, Any]] = []
    per_section: list[dict[str, Any]] = []
    total = 0
    for section in sorted(sections, key=lambda s: s.get("index", 0)):
        text = section.get("text") or ""
        word_count = count_chinese_characters(text)
        total += word_count
        updated.append({**section, "word_count": word_count})
        per_section.append(
            {
                "index": section.get("index"),
                "title": section.get("title"),
                "word_count": word_count,
                "word_budget": section.get("word_budget"),
                "style_violations": style_violations(text),
            }
        )

    min_words, max_words = (list(brief.get("target_word_count") or []) + [0, 0])[:2]
    full_text = "\n\n".join((s.get("text") or "") for s in updated)
    qa_report = {
        "title": meta.get("title", ""),
        "total_word_count": total,
        "section_count": len(updated),
        "target_word_count": [min_words, max_words],
        "in_target_range": (min_words <= total <= max_words) if max_words else None,
        "all_sections_have_text": all(s.get("text") for s in updated) if updated else False,
        "whole_text_style": style_metrics(full_text),
        "remaining_style_violations": style_violations(full_text),
        "sections": per_section,
    }
    return {SECTIONS_PATH: updated, "qa_report": qa_report}


def build_final_qa_stage() -> Stage:
    return Stage(
        name="final_qa",
        executor=final_qa_executor,
        reads=[SECTIONS_PATH, META_PATH, BRIEF_PATH],
        writes=[SECTIONS_PATH],
    )


# ---------------------------------------------------------------------------
# 组装:登记进 NodeRegistry,供 workflow.yaml 按名引用。
# ---------------------------------------------------------------------------

STAGE_NAMES_NEEDING_LLM = (
    "story_design",
    "outline_generation",
    "outline_critic",
    "section_drafting",
    "section_polish",
    "section_critic",
)


def build_node_registry(client_factory: ClientFactory, stage_models: dict[str, str] | None = None):
    """组装本场景的全部节点并登记进一个新的 NodeRegistry。

    Args:
        client_factory: 按 (节点名, model) 取 LLMClient 的工厂函数。
        stage_models:   workflow.yaml 里解析出的每个节点的生效 model(见
            engine.workflow.Workflow.resolve_stage_models);未标注过 model 的
            节点不出现在这个 dict 里,此时传给 client_factory 的 model 为 None。
    """
    from engine.workflow import NodeRegistry  # 延迟导入,避免与 workflow.py 循环依赖

    stage_models = stage_models or {}

    def client_for(stage_name: str) -> LLMClient:
        return client_factory(stage_name, stage_models.get(stage_name))

    registry = NodeRegistry()
    registry.register(build_input_parsing_stage())
    registry.register(build_story_design_stage(client_for("story_design")))
    registry.register(build_outline_generation_stage(client_for("outline_generation")))
    registry.register(build_outline_critic_stage(client_for("outline_critic")))
    registry.register(build_section_drafting_stage(client_for("section_drafting")))
    registry.register(build_section_polish_stage(client_for("section_polish")))
    registry.register(build_section_critic_stage(client_for("section_critic")))
    registry.register(build_final_qa_stage())
    return registry


__all__ = [
    "ClientFactory",
    "NEEDS_REVISION_KEY",
    "OUTLINE_LOOP_LAST_PATH",
    "SECTION_ITEM_PATH",
    "SECTION_REVIEW_LOOP_LAST_PATH",
    "STAGE_NAMES_NEEDING_LLM",
    "build_node_registry",
]
