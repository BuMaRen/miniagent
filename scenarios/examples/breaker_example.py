"""Breaker 示例 —— "break":predicate 为真时立刻终止最近的外层 Loop/ForEach。

和 continue_when 的分工(见 loop_example.py):continue_when 是 Loop 专属的
"是非器",只回答"这一轮算不算过";Breaker 是放进 body 里的一个普通 Node,回答的
是一个完全独立的问题——"不管这一轮/这一项算不算过,现在就提前结束整个循环"。
两者互不知晓对方存在。

本例:批量审批任务,一旦批准数达到配额(quota),后面的任务**一个都不再处理**
(相当于 Python 的 `for` 循环里的 `break`),不是"跳过这一项继续下一项"(那是
`continue` 的语义,ForEach 本身没有提供,如果需要"跳过当前项但继续处理下一项",
写法是让 body 里的节点判断条件后直接不做任何修改地返回,即"什么都不干"地过一遍
——不需要引擎专门支持)。

运行:python -m scenarios.examples.breaker_example
"""

from __future__ import annotations

from engine.context import LifecycleHooks, RunContext
from engine.primitives.foreach import ForEach
from engine.primitives.sequence import Sequence
from state.backends.memory import InMemoryStateStore

from scenarios.examples.nodes import TASK_LOOP_NAME, build_process_task_stage, build_quota_breaker
from scenarios.examples.state_schema import make_batch_state

TASKS = [
    {"id": "t1", "amount": 30, "status": "pending", "note": ""},
    {"id": "t2", "amount": 50, "status": "pending", "note": ""},
    {"id": "t3", "amount": 10, "status": "pending", "note": ""},  # 配额满了,轮不到它
    {"id": "t4", "amount": 20, "status": "pending", "note": ""},  # 同上
]


def build_workflow(*, threshold: int, quota: int) -> ForEach:
    return ForEach(
        name=TASK_LOOP_NAME,
        items_path="batch.tasks",
        # Breaker 放在 process_task 之后:先处理完当前这一项,再检查配额满没满——
        # 于是"刚好把配额用满的那一项"本身会被处理,配额满之后的项才被跳过。
        # 换成放在前面,则会在处理任何一项之前就先检查,语义不同,按需选择。
        body=Sequence(name=f"{TASK_LOOP_NAME}_body", nodes=[
            build_process_task_stage(threshold),
            build_quota_breaker(quota),
        ]),
    )


def main() -> None:
    ctx = RunContext(
        state=InMemoryStateStore(initial=make_batch_state(TASKS)),
        hooks=LifecycleHooks(before_loop_iteration=lambda name, i: print(f"  --- {name} 第 {i + 1} 项 ---")),
    )
    foreach = build_workflow(threshold=100, quota=2)
    print("ForEach + Breaker:批准数达到 2 就提前结束,后面的任务保持 pending 不处理:")
    result = foreach.run(ctx, {})
    print(f"\nForEach 返回: {result}")
    assert result.get("broken") is True   # ForEach 的返回值里带一个 broken 标记
    assert result["iterations"] == 2       # 只真正跑了 2 项(t1、t2),t3/t4 被跳过

    tasks = ctx.state.get("batch.tasks")
    print("最终状态:")
    for t in tasks:
        print(f"  {t}")
    assert [t["status"] for t in tasks] == ["approved", "approved", "pending", "pending"]
    assert ctx.state.get("batch.approved_count") == 2
    print("\n断言全部通过:t3/t4 完全没有被处理过(status 仍是初始值 pending)。")


if __name__ == "__main__":
    main()
