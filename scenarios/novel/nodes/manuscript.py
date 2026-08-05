"""全文统稿与润色(3.9)。"""

from __future__ import annotations

from engine.stage import Stage
from llm.client import LLMClient
from state.schema import StateSchema

from scenarios.novel import prompts
from scenarios.novel.nodes.common import CHAPTERS_PATH, FORESHADOWING_PATH, META_PATH, make_agent
from scenarios.novel.state_schema import CHAPTER, FORESHADOWING

MANUSCRIPT_ASSEMBLY_POLISH_OUTPUT_SCHEMA = StateSchema(
    "manuscript_assembly_polish_output",
    {CHAPTERS_PATH: [CHAPTER], FORESHADOWING_PATH: [FORESHADOWING]},
)


def build_manuscript_assembly_polish_stage(client: LLMClient) -> Stage:
    agent = make_agent(
        client, prompts.MANUSCRIPT_ASSEMBLY_POLISH, output_schema=MANUSCRIPT_ASSEMBLY_POLISH_OUTPUT_SCHEMA
    )
    return Stage(
        name="manuscript_assembly_polish",
        executor=agent.run,
        reads=[CHAPTERS_PATH, FORESHADOWING_PATH, META_PATH],
        writes=[CHAPTERS_PATH, FORESHADOWING_PATH],
        output_schema=MANUSCRIPT_ASSEMBLY_POLISH_OUTPUT_SCHEMA,
    )
