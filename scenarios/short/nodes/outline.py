"""分节大纲 + 大纲评审(outline_loop 的 body)。

生成与修订是同一个节点:游标为空就是生成,游标里带着上一轮的评审意见就是修订。
"""

from __future__ import annotations

from typing import Any

from engine.context import RunContext
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
from scenarios.short.state_schema import PAYOFF, SECTION
from scenarios.short.toolsets.structure import outline_problems

# Loop 的名字,同时用于拼出游标路径(loop_cursor_path)——workflow.py 组装时也要用
# 这个名字构造 Loop(name=OUTLINE_LOOP_NAME, ...),两处共用一份常量,不会各写一遍。
OUTLINE_LOOP_NAME = "outline_loop"
OUTLINE_LOOP_LAST_PATH = loop_cursor_path(OUTLINE_LOOP_NAME)

# 大纲阶段只产出 SECTION 的"计划字段",正文相关字段(text/summary/word_count/
# status)由代码填占位值——从 SECTION 投影出来而不是另抄一份,免得两边各改各的。
_OUTLINE_SECTION = {k: SECTION[k] for k in ("index", "title", "beat_summary", "payoff_note", "word_budget")}

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
    agent = make_agent(client, prompts.OUTLINE, output_schema=OUTLINE_AGENT_SCHEMA)

    def executor(ctx: RunContext, inputs: dict[str, Any]) -> dict[str, Any]:
        state = inputs.get("state", {})
        out = ask(
            agent,
            ctx,
            {
                prompts.KEY_BRIEF: state.get(BRIEF_PATH) or {},
                prompts.KEY_STORY: story_context(state),
                prompts.KEY_FEEDBACK: feedback_from(state, OUTLINE_LOOP_LAST_PATH),
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
    agent = make_agent(client, prompts.OUTLINE_CRITIC, output_schema=CRITIC_OUTPUT_SCHEMA)

    def executor(ctx: RunContext, inputs: dict[str, Any]) -> dict[str, Any]:
        state = inputs.get("state", {})
        brief = state.get(BRIEF_PATH) or {}
        sections = state.get(SECTIONS_PATH) or []
        payoffs = state.get(PAYOFFS_PATH) or []
        # 先算后问:确定性问题连同大纲一起交给模型,免得它把注意力浪费在数数上。
        auto_problems = outline_problems(sections, payoffs, brief.get("target_word_count") or [0, 0])
        verdict = ask(
            agent,
            ctx,
            {
                prompts.KEY_OUTLINE: {"sections": sections, "payoffs": payoffs},
                prompts.KEY_BRIEF: brief,
                prompts.KEY_STORY: story_context(state),
                prompts.KEY_AUTO_PROBLEMS: auto_problems,
            },
        )
        return merge_verdict(verdict, auto_problems)

    return Stage(
        name="outline_critic",
        executor=executor,
        reads=[BRIEF_PATH, META_PATH, CHARACTERS_PATH, SECTIONS_PATH, PAYOFFS_PATH],
        output_schema=CRITIC_OUTPUT_SCHEMA,
    )
