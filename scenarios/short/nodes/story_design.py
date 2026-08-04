"""故事骨架设计。"""

from __future__ import annotations

from typing import Any

from engine.context import RunContext
from engine.stage import Stage
from llm.client import LLMClient
from state.schema import StateSchema

from scenarios.short import prompts
from scenarios.short.nodes.common import (
    BRIEF_PATH,
    CHARACTERS_PATH,
    META_PATH,
    ask,
    make_agent,
)
from scenarios.short.state_schema import CHARACTER

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
    "story_design_output",
    {
        META_PATH: {"title": str, "logline": str, "one_line_hook": str, "core_conflict": str},
        CHARACTERS_PATH: [CHARACTER],
    },
)


def build_story_design_stage(client: LLMClient) -> Stage:
    agent = make_agent(client, prompts.STORY_DESIGN, output_schema=STORY_DESIGN_AGENT_SCHEMA)

    def executor(ctx: RunContext, inputs: dict[str, Any]) -> dict[str, Any]:
        state = inputs.get("state", {})
        out = ask(agent, ctx, {prompts.KEY_BRIEF: state.get(BRIEF_PATH) or {}})
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
