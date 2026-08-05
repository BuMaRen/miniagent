"""Loop 示例 —— "continue":同一份输入反复跑 body,直到判定不再要求重来。

场景:一份"提案金额"从 0 开始,每轮 propose_amount 把它加 step,review_amount
检查是否达到 minimum;没达到就把 needs_revision 设成 True——Loop 把 review_amount
刚产出的这份 outputs 交给 continue_when 这个判定谓词,谓词返回真,就从 body[0]
重开一轮,这就是"continue"(还要再来一轮)。真正的判定只发生在这一处:
`continue_when(ctx, outputs) -> bool`。引擎不认识 needs_revision 这个名字——
谓词内部写的是什么字段、要不要取反,都是场景自己的事,引擎只管调用这个函数、
取它的返回值真假(见 engine/primitives/loop.py,以及 nodes.py 的
needs_revision_continue_when)。

本文件依次演示:
  1. 正常收敛:轮数够,金额最终达标,Loop 判过退出。
  2. on_exceed=ACCEPT_LAST:轮数不够也不管,跑满 max_iterations 就放行最后一版。
  3. on_exceed=RAISE:轮数不够就直接报错,不允许"凑合放行"。
  4. on_exceed=ESCALATE_TO_CHECKPOINT:轮数不够就转人工裁决。

运行:python -m scenarios.examples.loop_example
"""

from __future__ import annotations

from typing import Any

from engine.context import CheckpointRequest, LifecycleHooks, RunContext
from engine.primitives.loop import Loop, LoopExceededError, OnExceed
from state.backends.memory import InMemoryStateStore

from scenarios.examples.nodes import (
    NEEDS_REVISION_KEY,
    PROPOSAL_LOOP_LAST_PATH,
    PROPOSAL_LOOP_NAME,
    make_propose_amount_stage,
    make_review_amount_stage,
    needs_revision_continue_when,
)
from scenarios.examples.state_schema import loop_demo_empty_state


def _hooks() -> LifecycleHooks:
    return LifecycleHooks(
        before_loop_iteration=lambda name, i: print(f"  --- {name} 第 {i + 1} 轮 ---"),
    )


def _build_loop(*, step: int, minimum: int, max_iterations: int, on_exceed: OnExceed) -> Loop:
    return Loop(
        name=PROPOSAL_LOOP_NAME,
        body=[make_propose_amount_stage(step), make_review_amount_stage(minimum)],
        continue_when=needs_revision_continue_when,
        max_iterations=max_iterations,
        on_exceed=on_exceed,
    )


def demo_converges() -> None:
    """金额每轮 +30,要求 >= 80,3 轮内能达标(30/60/90):第 3 轮通过,正常退出。"""
    print("\n=== 1. 正常收敛(3 轮内达标) ===")
    ctx = RunContext(state=InMemoryStateStore(initial=loop_demo_empty_state()), hooks=_hooks())
    loop = _build_loop(step=30, minimum=80, max_iterations=5, on_exceed=OnExceed.RAISE)
    outputs = loop.run(ctx, {})
    print(f"结果: {outputs}")
    assert outputs["_loop"] == {"name": PROPOSAL_LOOP_NAME, "iterations": 3, "exhausted": False}
    # 游标在循环真正结束时被清掉,不会泄漏给循环后面的节点(见 Loop._finish)。
    assert ctx.state.get(PROPOSAL_LOOP_LAST_PATH) is None


def demo_on_exceed_accept_last() -> None:
    """要求 >= 100,但只给 2 轮(2 轮最多到 60),必然跑满——ACCEPT_LAST 放行最后一版。"""
    print("\n=== 2. on_exceed=ACCEPT_LAST(跑满轮次也接受最后一版) ===")
    ctx = RunContext(state=InMemoryStateStore(initial=loop_demo_empty_state()), hooks=_hooks())
    loop = _build_loop(step=30, minimum=100, max_iterations=2, on_exceed=OnExceed.ACCEPT_LAST)
    outputs = loop.run(ctx, {})
    print(f"结果: {outputs}")
    assert outputs["_loop"]["exhausted"] is True
    assert outputs[NEEDS_REVISION_KEY] is True  # 最后一版其实还是没通过,只是被放行了
    print("注意:exhausted=True 说明这是被放行的,不是真通过——下游节点该不该信任它,")
    print("      由场景自己看 _loop.exhausted 决定,原语不替你掩盖这个事实。")


def demo_on_exceed_raise() -> None:
    """同样的设置,换成 RAISE:不允许凑合,直接报错终止。"""
    print("\n=== 3. on_exceed=RAISE(跑满轮次直接报错) ===")
    ctx = RunContext(state=InMemoryStateStore(initial=loop_demo_empty_state()), hooks=_hooks())
    loop = _build_loop(step=30, minimum=100, max_iterations=2, on_exceed=OnExceed.RAISE)
    try:
        loop.run(ctx, {})
    except LoopExceededError as exc:
        print(f"预期报错: {exc}")
    else:
        raise AssertionError("应该抛出 LoopExceededError")


def demo_on_exceed_escalate_to_checkpoint() -> None:
    """同样的设置,换成 ESCALATE_TO_CHECKPOINT:转人工裁决,而不是程序自己决定。"""
    print("\n=== 4. on_exceed=ESCALATE_TO_CHECKPOINT(跑满轮次转人工裁决) ===")

    def handler(request: CheckpointRequest) -> dict[str, Any]:
        print(f"  [人工裁决] {request.prompt}")
        print(f"  [人工裁决] 当前上下文: {request.context}")
        # 人工看了一眼,决定手动给个通过。
        return {NEEDS_REVISION_KEY: False, "feedback": "人工特批,金额虽不达标但可以接受"}

    ctx = RunContext(
        state=InMemoryStateStore(initial=loop_demo_empty_state()),
        checkpoint_handler=handler,
        hooks=_hooks(),
    )
    loop = _build_loop(step=30, minimum=100, max_iterations=2, on_exceed=OnExceed.ESCALATE_TO_CHECKPOINT)
    outputs = loop.run(ctx, {})
    print(f"结果: {outputs}")
    assert outputs[NEEDS_REVISION_KEY] is False  # 人工裁决覆盖了原本的判否


if __name__ == "__main__":
    demo_converges()
    demo_on_exceed_accept_last()
    demo_on_exceed_raise()
    demo_on_exceed_escalate_to_checkpoint()
