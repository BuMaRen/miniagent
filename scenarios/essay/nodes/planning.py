from typing import Any

from engine.context import RunContext
from engine.primitives.loop import loop_cursor_path
from engine.stage import Node, Stage
from llm.client import LLMClient
from scenarios.essay import prompts
from scenarios.essay.nodes.common import make_agent
from scenarios.essay.schemas.state import BRIEF_PATH, PLANNING_OUTPUT_SCHEMA, PLAN_PATH
from scenarios.essay.trend import load_monthly_trend

PLANNING_CHECKPOINT_LOOP_NAME = "planning_checkpoint_loop"


def _planning_executor(agent) -> Any:
    def _run(ctx: RunContext, inputs: dict) -> dict:
        # monthly_trend 不是状态存储里的一份用户输入,而是每月手动替换的外部
        # 文件(见 trend.py),每次运行都重新读一遍,替换文件后下一次运行立即
        # 生效,不需要经过 reads/StateStore。
        inputs["monthly_trend"] = load_monthly_trend()
        return agent.run(ctx, inputs)

    return _run


def build_planning_node(client: LLMClient) -> Node:
    """情节规划节点。不接 AI 审核(需求原话),是否通过由人工判断。

    reads 里带上 planning_checkpoint_loop 的游标:首轮该值为 None,视为
    "无历史反馈,按 brief 首次规划";若流程开启了人工审核且上一轮被驳回,
    游标里会带着上一版 essay_state.plan 与人工的 {approved: false, feedback}
    (见 engine/primitives/loop.py 的游标发布规则),供本节点参考反馈重新规划。

    额外注入 monthly_trend(平台当月的热门方向参考,见 trend.py),该字段独立
    于 brief,每月替换 monthly_trend.md 即可更新,不需要改代码。
    """
    agent = make_agent(
        client=client,
        system_prompt=prompts.PLANNING,
        output_schema=PLANNING_OUTPUT_SCHEMA,
    )

    return Stage(
        name="planning",
        executor=_planning_executor(agent),
        reads=[BRIEF_PATH, loop_cursor_path(PLANNING_CHECKPOINT_LOOP_NAME)],
        writes=[PLAN_PATH],
        output_schema=PLANNING_OUTPUT_SCHEMA,
    )
