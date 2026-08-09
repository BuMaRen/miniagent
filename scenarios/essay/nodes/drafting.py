from typing import Any

from engine.context import RunContext
from engine.stage import Node, Stage
from llm.client import LLMClient
from scenarios.essay import prompts
from scenarios.essay.nodes.common import annotate_word_counts, make_agent
from scenarios.essay.schemas.state import (
    DRAFT_OUTPUT_SCHEMA,
    DRAFT_PATH,
    PLAN_PATH,
    REVIEW_PATH,
)


def _with_word_counts(agent) -> Any:
    """包一层 agent.run:模型给的 word_count 不可信,用代码重新统计后再返回。

    只是丰富同一份 outputs 里已声明的字段,不需要额外状态路径,直接用一个
    普通函数包裹即可(不需要 engine/stage.py 文档里"满足 Node 协议的包装类"
    那种重量级模式——那是给需要写额外状态路径的场景用的)。
    """

    def _run(ctx: RunContext, inputs: dict) -> dict:
        outputs = agent.run(ctx, inputs)
        annotate_word_counts(outputs.get(DRAFT_PATH, []))
        return outputs

    return _run


def build_first_draft_node(client: LLMClient) -> Node:
    agent = make_agent(
        client=client,
        system_prompt=prompts.FIRST_DRAFT,
        output_schema=DRAFT_OUTPUT_SCHEMA,
    )

    return Stage(
        name="first_draft",
        executor=_with_word_counts(agent),
        reads=[PLAN_PATH],
        writes=[DRAFT_PATH],
        output_schema=DRAFT_OUTPUT_SCHEMA,
    )


def build_redraft_node(client: LLMClient) -> Node:
    agent = make_agent(
        client=client,
        system_prompt=prompts.REDRAFT,
        output_schema=DRAFT_OUTPUT_SCHEMA,
    )

    return Stage(
        name="redraft",
        executor=_with_word_counts(agent),
        # REVIEW_PATH 由 review 节点的 writes 直接落到真实 state(不是只发布到
        # loop 游标),这里直接读即可,不需要 loop_cursor_path——游标机制只在
        # "上一轮的产出没有正式的 state 路径可落"时才需要(对比
        # nodes/planning.py:Checkpoint 的人工反馈就没有对应的 state 路径)。
        reads=[PLAN_PATH, DRAFT_PATH, REVIEW_PATH],
        writes=[DRAFT_PATH],
        output_schema=DRAFT_OUTPUT_SCHEMA,
    )
