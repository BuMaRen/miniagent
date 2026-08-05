"""判断是否还有 drafted 状态的用例待处理。

对应 workflow.md "Node" 一节的第 3 点:"判断结束使用一个 no-agent 的 Node"。
不调用任何 LLM,只读当前状态里的 drafted_cases 数量,把结果交给
test_case_redraft_loop 的 continue_when 判定是否要再来一轮 redraft+review。

放在 Loop body 的最后一个位置(redraft -> review -> 本节点)而不是最前面:
workflow.md 画的是"先判断、再评审"的顺序,但 workflow.py 里进入这个 Loop 之前
已经在 test_case_first_draft 这个 Sequence 里跑过一轮 first_draft+review 了,
所以本 Loop 天然是"do-while"语义——判断动作放在每一轮的末尾,效果等价。
"""

from __future__ import annotations

from typing import Any

from engine.context import RunContext
from engine.stage import Node, Stage
from scenarios.testdesign.schemas.state import DRAFT_PATH

# Loop 的 continue_when 判定字段:真 = drafted_cases 非空、还要再来一轮。
# 只有这个节点的 outputs 会带这个字段——redraft/review 的输出里没有它,
# continue_when 用 .get(..., False) 读它们时天然落到 False,不会被误判成
# "要重开一轮"(同一份签名多处复用的约定,见 engine/primitives/loop.py
# 模块 docstring)。
NEEDS_REDRAFT_KEY = "needs_redraft"


def build_pending_check_node() -> Node:
    def _check(ctx: RunContext, inputs: dict[str, Any]) -> dict[str, Any]:
        pending = ctx.state.get(DRAFT_PATH) or []
        return {NEEDS_REDRAFT_KEY: len(pending) > 0}

    return Stage(name="pending_check", executor=_check)
