from engine.stage import Node, Stage
from llm.client import LLMClient
from scenarios.testdesign import prompts
from scenarios.testdesign.nodes.common import make_agent
from scenarios.testdesign.schemas.state import FIRST_DRAFT_OUTPUT_SCHEMA, DRAFT_PATH, REQUIREMENT_DOC_PATH


def build_first_draft_node(client: LLMClient) -> Node:
    agent = make_agent(
        client=client,
        system_prompt=prompts.FIRST_DRAFT,
        output_schema=FIRST_DRAFT_OUTPUT_SCHEMA,
    )

    return Stage(
        name="first_draft",
        executor=agent.run,
        reads=[REQUIREMENT_DOC_PATH],
        writes=[DRAFT_PATH],
        output_schema=FIRST_DRAFT_OUTPUT_SCHEMA,
    )
