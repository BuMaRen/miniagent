"""立意扩展(3.2)。"""

from __future__ import annotations

from engine.stage import Stage
from llm.client import LLMClient
from state.schema import StateSchema

from scenarios.novel import prompts
from scenarios.novel.nodes.common import META_PATH, make_agent
from scenarios.novel.toolsets.research import RESEARCH_TOOLSET

CONCEPT_EXPANSION_OUTPUT_SCHEMA = StateSchema(
    "concept_expansion_output",
    {META_PATH: {"logline": str, "theme": str, "core_conflict": str}},
)


def build_concept_expansion_stage(client: LLMClient) -> Stage:
    agent = make_agent(
        client,
        prompts.CONCEPT_EXPANSION,
        toolsets=(RESEARCH_TOOLSET,),
        output_schema=CONCEPT_EXPANSION_OUTPUT_SCHEMA,
    )
    return Stage(
        name="concept_expansion",
        executor=agent.run,
        reads=[META_PATH],
        writes=[META_PATH],
        output_schema=CONCEPT_EXPANSION_OUTPUT_SCHEMA,
    )
