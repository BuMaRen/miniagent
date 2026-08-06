from engine.stage import Node, Stage
from llm.client import LLMClient
from scenarios.example import prompts
from scenarios.example.nodes.common import make_agent
from scenarios.example.schemas.state import REDRAFT_OUTPUT_SCHEMA, DRAFT_PATH, REQUIREMENT_DOC_PATH


def build_redraft_node(client: LLMClient) -> Node:
    agent = make_agent(
        client=client,
        system_prompt=prompts.REDRAFT,
        output_schema=REDRAFT_OUTPUT_SCHEMA,
    )

    return Stage(
        name="redraft",
        executor=agent.run,
        reads=[REQUIREMENT_DOC_PATH, DRAFT_PATH],
        writes=[DRAFT_PATH],
        output_schema=REDRAFT_OUTPUT_SCHEMA,
    )
