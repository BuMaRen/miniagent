from engine.stage import Node, Stage
from llm.client import LLMClient
from scenarios.testdesign.nodes.common import make_agent
from scenarios.testdesign.schemas.state import (
    DEPRECATED_PATH,
    DRAFT_PATH,
    REVIEW_OUTPUT_SCHEMA,
    REVIEWED_PATH,
    REQUIREMENT_DOC_PATH,
)

_REVIEW_PROMPT = """你需要根据用户提供的 markdown 需求文档和测试用例初稿，生成评审意见"""

def build_review_node(client: LLMClient) -> Node:
    agent = make_agent(
        client=client,
        system_prompt=_REVIEW_PROMPT,
        output_schema=REVIEW_OUTPUT_SCHEMA,
    )

    return Stage(
        name="review",
        executor=agent.run,
        reads=[DRAFT_PATH, REQUIREMENT_DOC_PATH],
        writes=[DRAFT_PATH, DEPRECATED_PATH, REVIEWED_PATH],
        output_schema=REVIEW_OUTPUT_SCHEMA,
    )
