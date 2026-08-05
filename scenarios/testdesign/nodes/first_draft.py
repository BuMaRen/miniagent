from engine.stage import Node, Stage
from llm.client import LLMClient
from scenarios.testdesign.nodes.common import make_agent
from scenarios.testdesign.schemas.state import FIRST_DRAFT_OUTPUT_SCHEMA, DRAFT_PATH, REQUIREMENT_DOC_PATH

_FIRST_DRAFT_PROMPT = """你需要根据用户提供的 markdown 需求文档，生成一版测试用例初稿"""


def build_first_draft_node(client: LLMClient) -> Node:
    agent = make_agent(
        client=client,
        system_prompt=_FIRST_DRAFT_PROMPT,
        output_schema=FIRST_DRAFT_OUTPUT_SCHEMA,
    )

    return Stage(
        name="first_draft",
        executor=agent.run,
        reads=[REQUIREMENT_DOC_PATH],
        writes=[DRAFT_PATH],
        output_schema=FIRST_DRAFT_OUTPUT_SCHEMA,
    )
