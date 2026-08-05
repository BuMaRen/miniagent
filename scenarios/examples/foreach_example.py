"""ForEach 示例 —— 对列表里的每个元素重复跑一遍 body,直到列表耗尽。

和 Loop 的分工:Loop 反复处理**同一份**数据、由一个判定决定停;ForEach 遍历
**不同**的元素、由数据耗尽决定停。ForEach 只负责"重复"这一件事,不负责
"连贯性"——"后面的项能看到前面项的产物"是 body 里的 Stage 读写共享 State 的
自然结果,不是 ForEach 塞了什么魔法字段(见 engine/primitives/foreach.py)。

运行:python -m scenarios.examples.foreach_example
"""

from __future__ import annotations

from engine.context import LifecycleHooks, RunContext
from engine.primitives.foreach import ForEach
from state.backends.memory import InMemoryStateStore

from scenarios.examples.nodes import TASK_LOOP_NAME, build_process_task_stage
from scenarios.examples.state_schema import make_batch_state

TASKS = [
    {"id": "t1", "amount": 30, "status": "pending", "note": ""},
    {"id": "t2", "amount": 120, "status": "pending", "note": ""},
    {"id": "t3", "amount": 80, "status": "pending", "note": ""},
]


def build_workflow(threshold: int) -> ForEach:
    return ForEach(
        name=TASK_LOOP_NAME,
        items_path="batch.tasks",
        body=build_process_task_stage(threshold),
    )


def main() -> None:
    ctx = RunContext(
        state=InMemoryStateStore(initial=make_batch_state(TASKS)),
        hooks=LifecycleHooks(before_loop_iteration=lambda name, i: print(f"  --- {name} 第 {i + 1} 项 ---")),
    )
    foreach = build_workflow(threshold=100)
    print("ForEach 逐个处理任务(金额 <= 100 批准):")
    result = foreach.run(ctx, {})
    print(f"\nForEach 返回: {result}")

    tasks = ctx.state.get("batch.tasks")
    print("最终状态:")
    for t in tasks:
        print(f"  {t}")
    assert [t["status"] for t in tasks] == ["approved", "rejected", "approved"]
    assert ctx.state.get("batch.approved_count") == 2
    # 遍历完成后,当前元素游标会被清掉,不泄漏给后续节点。
    assert ctx.state.get("_foreach.task_loop.item") is None
    print("\n断言全部通过。")


if __name__ == "__main__":
    main()
