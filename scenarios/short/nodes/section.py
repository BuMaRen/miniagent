"""逐节撰写 / 语言精修 / 审校。

撰写只管情节与爽点,精修只管语言——两件事要的注意力不同,合成一个节点时模型总会
顾此失彼(让它一边编爆点一边数句长,两头都糊)。

workflow.py 里 section_loop(ForEach)的 body 是 Sequence([撰写]保底拿到一份初稿)
接一个 section_review_loop(Loop, body=[精修, 审校]):精修在前、审校在后,判否就
从 body[0] 重开一轮精修,判过则这一节到此为止。撰写只跑这一次、不进循环——情节
与爽点定死之后不再重赌;循环只反复"精修 -> 审校",成本随质量需要而变,而不是像
撰写那样一次性摊死。
"""

from __future__ import annotations

import logging
from typing import Any

from engine.context import RunContext
from engine.primitives.foreach import foreach_item_path
from engine.primitives.loop import loop_cursor_path
from engine.stage import Stage
from llm.client import LLMClient
from state.schema import StateSchema

from scenarios.short import prompts
from scenarios.short.nodes.common import (
    BRIEF_PATH,
    CHARACTERS_PATH,
    CRITIC_OUTPUT_SCHEMA,
    META_PATH,
    PAYOFFS_PATH,
    SECTIONS_PATH,
    ask,
    feedback_from,
    make_agent,
    merge_verdict,
    story_context,
)
from scenarios.short.state_schema import SECTION
from scenarios.short.toolsets.structure import section_length_problem
from scenarios.short.toolsets.style import (
    STYLE_TOOLSET,
    count_chinese_characters,
    style_metrics,
    style_violations,
)

logger = logging.getLogger(__name__)

# ForEach 的名字(逐节遍历)和内层 Loop 的名字(精修 -> 审校),同时用于拼出各自的
# 游标路径——workflow.py 组装时也要用这两个名字构造 ForEach/Loop,两处共用一份
# 常量,不会各写一遍。
SECTION_LOOP_NAME = "section_loop"
SECTION_REVIEW_LOOP_NAME = "section_review_loop"
SECTION_ITEM_PATH = foreach_item_path(SECTION_LOOP_NAME)
SECTION_REVIEW_LOOP_LAST_PATH = loop_cursor_path(SECTION_REVIEW_LOOP_NAME)

SECTION_DRAFTING_AGENT_SCHEMA = StateSchema("section_drafting_agent_output", {"text": str, "summary": str})
SECTION_POLISH_AGENT_SCHEMA = StateSchema("section_polish_agent_output", {"text": str, "revision_notes": str})

# 两个写作节点对 Stage 的输出契约是同一份:整份 sections(交给 writes 写回)+
# 本节 index 与正文。text 这个通道①字段只在同一轮内紧邻的下一个节点有用
# (调试、日志);跨 Loop 轮次的正文一律靠 _section_text() 从 state 里读,见
# 该函数的说明。
SECTION_WRITE_OUTPUT_SCHEMA = StateSchema(
    "section_write_output", {SECTIONS_PATH: [SECTION], "section_index": int, "text": str}
)


def _replace_section(sections: list[dict], index: Any, **updates: Any) -> list[dict]:
    """返回一份新的 sections:把 index 对应的那一节按 updates 更新,其余原样。"""
    return [{**s, **updates} if s.get("index") == index else s for s in sections]


def _previous_digest(sections: list[dict], current_index: Any) -> list[dict]:
    """前情提要:此前各节的摘要,不含正文。

    正文只回传上一节的结尾(见 _tail),其余用摘要——短篇总共不到一万字,整篇塞
    进去当然塞得下,但每节都塞一遍会让上下文与费用随节数平方增长,而且模型更容易
    顺着旧句式复读。
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

    section_polish/section_critic 被包进 section_review_loop:Loop 每轮都从同一份
    inputs 重新开始(见 engine/primitives/loop.py 的说明),通道①的 "text" 只保真
    同一轮内紧邻的两个节点,跨轮次会被重置回循环最初收到的那份 inputs,看不到上一
    轮精修的结果。只有 ctx.state 是跨轮次可靠的,所以这两个节点都必须从这里读正文,
    不能再依赖通道①。
    """
    section = next((s for s in sections if s.get("index") == index), None)
    return str((section or {}).get("text") or "")


def _current_section(state: dict[str, Any]) -> dict[str, Any]:
    """ForEach 发布在游标上的"本节大纲"。"""
    return state.get(SECTION_ITEM_PATH) or {}


def build_section_drafting_stage(client: LLMClient) -> Stage:
    agent = make_agent(client, prompts.SECTION_DRAFTING, output_schema=SECTION_DRAFTING_AGENT_SCHEMA)

    def executor(ctx: RunContext, inputs: dict[str, Any]) -> dict[str, Any]:
        state = inputs.get("state", {})
        sections = state.get(SECTIONS_PATH) or []
        current = _current_section(state)
        index = current.get("index")
        following = next((s for s in sections if s.get("index") == (index or 0) + 1), None)

        out = ask(
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
                prompts.KEY_STORY: story_context(state),
                prompts.KEY_BRIEF: state.get(BRIEF_PATH) or {},
                prompts.KEY_FEEDBACK: feedback_from(state, SECTION_REVIEW_LOOP_LAST_PATH),
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
    agent = make_agent(
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
        # section_review_loop 里,审校判否时会带着具体意见再跑一轮——KEY_FEEDBACK
        # 非空就是上一轮被驳回的理由。
        out = ask(
            agent,
            ctx,
            {
                prompts.KEY_SECTION: current,
                prompts.KEY_TEXT: text,
                prompts.KEY_BUDGET: current.get("word_budget"),
                prompts.KEY_BRIEF: state.get(BRIEF_PATH) or {},
                prompts.KEY_METRICS: style_metrics(text),
                prompts.KEY_AUTO_PROBLEMS: problems,
                prompts.KEY_FEEDBACK: feedback_from(state, SECTION_REVIEW_LOOP_LAST_PATH),
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
    agent = make_agent(
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

        verdict = ask(
            agent,
            ctx,
            {
                prompts.KEY_SECTION: current,
                prompts.KEY_TEXT: text,
                prompts.KEY_PREVIOUS: _previous_digest(sections, index),
                prompts.KEY_STORY: story_context(state),
                prompts.KEY_BRIEF: state.get(BRIEF_PATH) or {},
                prompts.KEY_METRICS: style_metrics(text),
                prompts.KEY_AUTO_PROBLEMS: auto_problems,
            },
        )
        return merge_verdict(verdict, auto_problems)

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
