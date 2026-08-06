from engine.stage import Node, Stage
from llm.client import LLMClient
from scenarios.example import prompts
from scenarios.example.nodes.common import make_agent
from scenarios.example.schemas.state import (
    DEPRECATED_PATH,
    DRAFT_PATH,
    REVIEW_OUTPUT_SCHEMA,
    REVIEWED_PATH,
    REQUIREMENT_DOC_PATH,
)


def build_review_node(client: LLMClient) -> Node:
    agent = make_agent(
        client=client,
        system_prompt=prompts.REVIEW,
        output_schema=REVIEW_OUTPUT_SCHEMA,
    )

    return Stage(
        name="review",
        executor=agent.run,
        # 需求方评审需要看到 drafted/reviewed/deprecated 三者(workflow.md:
        # "需求 可以访问 drafted、reviewed、deprecated"),否则它给不出累积后的
        # 完整快照——而 writes 是整表覆盖(见 state/backends/memory.py 的 patch
        # 语义),读不到旧值就会把上一轮已经归档的用例覆盖掉。
        reads=[DRAFT_PATH, REVIEWED_PATH, DEPRECATED_PATH, REQUIREMENT_DOC_PATH],
        writes=[DRAFT_PATH, DEPRECATED_PATH, REVIEWED_PATH],
        output_schema=REVIEW_OUTPUT_SCHEMA,
    )
