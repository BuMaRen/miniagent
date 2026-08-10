from typing import Any

from engine.context import RunContext
from engine.stage import Node, Stage
from llm.client import LLMClient
from scenarios.essay import prompts
from scenarios.essay.nodes.common import make_agent
from scenarios.essay.schemas.state import DRAFT_PATH, META_OUTPUT_SCHEMA, META_PATH, PLAN_PATH
from scenarios.essay.tags import load_tag_taxonomy


def _meta_executor(agent) -> Any:
    def _run(ctx: RunContext, inputs: dict) -> dict:
        # tag_taxonomy 不是状态存储里的用户输入,而是每月/随时可替换的外部
        # 文件(见 tags.py),每次运行都重新读一遍,替换文件后下一次运行立即
        # 生效,不需要经过 reads/StateStore(与 planning 节点注入
        # monthly_trend 的方式一致,见 nodes/planning.py)。
        inputs["tag_taxonomy"] = load_tag_taxonomy()
        return agent.run(ctx, inputs)

    return _run


def build_meta_node(client: LLMClient) -> Node:
    """标题/简介/分类标签节点:定稿(通过审核的正文)之后产出平台展示用的
    元信息,始终执行(不像封面那样受 generate_cover 开关控制)。
    """
    agent = make_agent(
        client=client,
        system_prompt=prompts.STORY_META,
        output_schema=META_OUTPUT_SCHEMA,
    )

    return Stage(
        name="meta",
        executor=_meta_executor(agent),
        reads=[PLAN_PATH, DRAFT_PATH],
        writes=[META_PATH],
        output_schema=META_OUTPUT_SCHEMA,
    )
