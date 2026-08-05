"""角色与世界观设计(3.3)。"""

from __future__ import annotations

from engine.stage import Stage
from llm.client import LLMClient
from state.schema import StateSchema

from scenarios.novel import prompts
from scenarios.novel.nodes.common import CHARACTERS_PATH, META_PATH, WORLD_PATH, make_agent
from scenarios.novel.state_schema import CHARACTER, WORLD_ENTRY
from scenarios.novel.toolsets.research import RESEARCH_TOOLSET

CHARACTER_WORLD_DESIGN_OUTPUT_SCHEMA = StateSchema(
    "character_world_design_output",
    {
        META_PATH: {"title": str},
        CHARACTERS_PATH: [CHARACTER],
        WORLD_PATH: [WORLD_ENTRY],
    },
)


def build_character_world_design_stage(client: LLMClient) -> Stage:
    agent = make_agent(
        client,
        prompts.CHARACTER_WORLD_DESIGN,
        toolsets=(RESEARCH_TOOLSET,),
        output_schema=CHARACTER_WORLD_DESIGN_OUTPUT_SCHEMA,
    )
    return Stage(
        name="character_world_design",
        executor=agent.run,
        reads=[META_PATH],
        writes=[META_PATH, CHARACTERS_PATH, WORLD_PATH],
        output_schema=CHARACTER_WORLD_DESIGN_OUTPUT_SCHEMA,
    )
