"""组合示例 —— 在同一个 Workflow 里同时看到 "continue" 和 "break"。

场景:一批任务,金额从各自的起始值开始,每一项都要"逐轮加价谈判"直到达到最低
金额(Loop + continue_when,谈判轮次超限就放弃,不强求每一项都成交)——这是
"continue":同一个任务反复重试。谈判定稿之后,一旦全局批准数达到配额,后面排
队的任务**整批不再处理**——这是"break":跳出的是外层的 ForEach,而不是当前
这一项的 Loop。

两者的关键区别,靠这个例子应该能看得很清楚:
  · continue(Loop.continue_when)—— 粒度是"这一项内部再试一次",跳出后紧接着
    走向该项的下一步(定稿),不影响其它项。
  · break(Breaker)—— 粒度是"整个遍历到此为止",跳出后直接结束 ForEach,后面
    的项连碰都不会被碰一下。

流程结构:

    ForEach(tasks):
        Sequence:
          Loop(negotiate_amount -> negotiate_review, continue_when=...)   # continue
          finalize_task                                                   # 定稿
          Breaker(quota reached)                                          # break

运行:python -m scenarios.examples.combined_example
"""

from __future__ import annotations

from engine.context import LifecycleHooks, RunContext
from engine.primitives.foreach import ForEach
from engine.primitives.loop import Loop, OnExceed
from engine.primitives.sequence import Sequence
from state.backends.memory import InMemoryStateStore

from scenarios.examples.nodes import (
    NEGOTIATE_LOOP_NAME,
    TASK_LOOP_NAME,
    build_finalize_task_stage,
    build_quota_breaker,
    make_negotiate_amount_stage,
    make_negotiate_review_stage,
    needs_revision_continue_when,
)
from scenarios.examples.state_schema import make_batch_state

# t1: 10 -> 25 -> 40 -> 55(第 3 轮达标,谈判成功)
# t2: 40 -> 55(第 1 轮就达标,谈判成功)——到这里累计批准 2 个,已达配额
# t3/t4:配额已满,ForEach 直接 break,连 Loop 都不会被跑一次
TASKS = [
    {"id": "t1", "amount": 10, "status": "pending", "note": ""},
    {"id": "t2", "amount": 40, "status": "pending", "note": ""},
    {"id": "t3", "amount": -100, "status": "pending", "note": ""},  # 明显达不到,若被跑到会验证失败
    {"id": "t4", "amount": 100, "status": "pending", "note": ""},
]

STEP = 15
MINIMUM = 50
MAX_ROUNDS = 3
QUOTA = 2


def build_workflow() -> ForEach:
    negotiate_loop = Loop(
        name=NEGOTIATE_LOOP_NAME,
        body=[make_negotiate_amount_stage(STEP), make_negotiate_review_stage(MINIMUM)],
        continue_when=needs_revision_continue_when,
        max_iterations=MAX_ROUNDS,
        on_exceed=OnExceed.ACCEPT_LAST,  # 全自动流程,没有人在等着裁决,不能升级人工
    )
    return ForEach(
        name=TASK_LOOP_NAME,
        items_path="batch.tasks",
        body=Sequence(
            name=f"{TASK_LOOP_NAME}_body",
            nodes=[negotiate_loop, build_finalize_task_stage(), build_quota_breaker(QUOTA)],
        ),
    )


def main() -> None:
    ctx = RunContext(
        state=InMemoryStateStore(initial=make_batch_state(TASKS)),
        hooks=LifecycleHooks(
            before_loop_iteration=lambda name, i: print(f"  --- {name} 第 {i + 1} {'项' if name == TASK_LOOP_NAME else '轮'} ---")
        ),
    )
    result = build_workflow().run(ctx, {})
    print(f"\nForEach 返回: {result}")

    tasks = ctx.state.get("batch.tasks")
    print("最终状态:")
    for t in tasks:
        print(f"  {t}")

    assert result.get("broken") is True
    assert result["iterations"] == 2   # 只有 t1、t2 真正被处理过,t3/t4 连 Loop 都没进
    assert [t["status"] for t in tasks] == ["approved", "approved", "pending", "pending"]
    assert ctx.state.get("batch.approved_count") == 2
    print(
        "\n断言通过:t1 谈判了 3 轮才达标(continue 在起作用),t2 谈判 1 轮就达标;"
        "\n配额在 t2 之后被打满,t3/t4 完全没有进入过 Loop(break 在起作用,"
        "\n不是'谈判失败被拒绝',是'压根没轮到它们')。"
    )


if __name__ == "__main__":
    main()
