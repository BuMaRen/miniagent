from engine.primitives.loop import loop_cursor_path
from engine.stage import Node, Stage
from llm.client import LLMClient
from scenarios.essay import prompts
from scenarios.essay.nodes.common import make_agent
from scenarios.essay.schemas.state import BRIEF_PATH, PLANNING_OUTPUT_SCHEMA, PLAN_PATH

PLANNING_CHECKPOINT_LOOP_NAME = "planning_checkpoint_loop"


def build_planning_node(client: LLMClient) -> Node:
    """情节规划节点。不接 AI 审核(需求原话),是否通过由人工判断。

    reads 里带上 planning_checkpoint_loop 的游标:首轮该值为 None,视为
    "无历史反馈,按 brief 首次规划";若流程开启了人工审核且上一轮被驳回,
    游标里会带着上一版 essay_state.plan 与人工的 {approved: false, feedback}
    (见 engine/primitives/loop.py 的游标发布规则),供本节点参考反馈重新规划。
    """
    agent = make_agent(
        client=client,
        system_prompt=prompts.PLANNING,
        output_schema=PLANNING_OUTPUT_SCHEMA,
    )

    return Stage(
        name="planning",
        executor=agent.run,
        reads=[BRIEF_PATH, loop_cursor_path(PLANNING_CHECKPOINT_LOOP_NAME)],
        writes=[PLAN_PATH],
        output_schema=PLANNING_OUTPUT_SCHEMA,
    )
