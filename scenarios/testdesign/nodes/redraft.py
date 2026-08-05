from engine.stage import Node, Stage
from llm.client import LLMClient
from scenarios.testdesign.nodes.common import make_agent
from scenarios.testdesign.schemas.state import REDRAFT_OUTPUT_SCHEMA, DRAFT_PATH, REQUIREMENT_DOC_PATH

_REDRAFT_PROMPT = """你需要根据用户提供的 markdown 需求文档, 测试用例初稿以及用例中携带的需求方的反馈修改用例, 生成一版测试用例修订稿"""


def build_redraft_node(client: LLMClient) -> Node:
    agent = make_agent(
        client=client,
        system_prompt=_REDRAFT_PROMPT,
        output_schema=REDRAFT_OUTPUT_SCHEMA,
    )

    return Stage(
        name="redraft",
        executor=agent.run,
        reads=[REQUIREMENT_DOC_PATH, DRAFT_PATH],
        writes=[DRAFT_PATH],
        output_schema=REDRAFT_OUTPUT_SCHEMA,
    )
