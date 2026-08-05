"""Checkpoint 示例 —— 人工断点:同步向外部要一次输入,拿到答案后立刻继续。

两段演示:
  1. 单独使用:流程跑到 Checkpoint 就暂停,通过 ctx.checkpoint_handler 拿到人工
     输入,校验通过后合并进 inputs 继续往下走;没配置 handler 时直接报错(不是
     "挂起等以后再说"的意思,见 engine/primitives/checkpoint.py 模块 docstring)。
  2. 和 Loop 组合:把 Checkpoint 放进 Loop 的 body 末尾(AI 评审之后),"零成本"
     组合出"AI 先挡、通过后人工再把关"——AI 判否时 Loop 已经短路,人工根本不会
     被打扰;人工判否时同样把 needs_revision 置真,驱动下一轮从头重写(这正是
     "continue" 和 Checkpoint 的典型配合,novel 场景的 confirm_outline/
     chapter_pause 就是这个模式,见 scenarios/novel/nodes/outline.py)。

运行:python -m scenarios.examples.checkpoint_example
"""

from __future__ import annotations

from typing import Any

from engine.context import CheckpointRequest, LifecycleHooks, RunContext
from engine.primitives.checkpoint import Checkpoint
from engine.primitives.loop import Loop
from state.backends.memory import InMemoryStateStore

from scenarios.examples.nodes import (
    CRITIC_SCHEMA,
    NEEDS_REVISION_KEY,
    PROPOSAL_LOOP_NAME,
    make_propose_amount_stage,
    make_review_amount_stage,
    needs_revision_continue_when,
)
from scenarios.examples.state_schema import loop_demo_empty_state


def demo_standalone() -> None:
    print("\n=== 1. 单独使用 Checkpoint ===")

    checkpoint = Checkpoint(
        name="confirm_amount",
        prompt="请确认金额是否可以放行",
        resume_input_schema=CRITIC_SCHEMA,
    )

    # 1a. 没有配置 checkpoint_handler:直接报错,不是静默挂起。
    ctx_no_handler = RunContext(state=InMemoryStateStore())
    try:
        checkpoint.run(ctx_no_handler, {"amount": 50})
    except RuntimeError as exc:
        print(f"  没有 handler 时的预期报错: {exc}")

    # 1b. 配置一个总是批准的 handler。
    def auto_approve(request: CheckpointRequest) -> dict[str, Any]:
        print(f"  [handler] 收到请求 {request.name!r},context={request.context}")
        return {NEEDS_REVISION_KEY: False, "feedback": ""}

    ctx = RunContext(state=InMemoryStateStore(), checkpoint_handler=auto_approve)
    result = checkpoint.run(ctx, {"amount": 50})
    print(f"  Checkpoint 返回(流入的 inputs 与人工输入合并): {result}")
    assert result == {"amount": 50, NEEDS_REVISION_KEY: False, "feedback": ""}

    # 1c. resume_input_schema 会校验 handler 的返回值,格式不对直接报错。
    def bad_handler(request: CheckpointRequest) -> dict[str, Any]:
        return {"wrong_key": True}

    ctx_bad = RunContext(state=InMemoryStateStore(), checkpoint_handler=bad_handler)
    try:
        checkpoint.run(ctx_bad, {"amount": 50})
    except Exception as exc:  # SchemaError
        print(f"  handler 返回格式不对时的预期报错: {exc}")


def demo_inside_loop() -> None:
    print("\n=== 2. Checkpoint 放进 Loop.body 末尾:AI 通过后再问人 ===")

    calls = {"human_asked": 0}

    def handler(request: CheckpointRequest) -> dict[str, Any]:
        calls["human_asked"] += 1
        # 第一次人工不满意(即使 AI 已经放行),要求继续加价;第二次才批准。
        if calls["human_asked"] == 1:
            print("  [人工] 第一次:金额还是不够有诚意,打回重写")
            return {NEEDS_REVISION_KEY: True, "feedback": "人工觉得还应该再加一点"}
        print("  [人工] 第二次:可以了,批准")
        return {NEEDS_REVISION_KEY: False, "feedback": ""}

    confirm = Checkpoint(name="confirm_amount", resume_input_schema=CRITIC_SCHEMA)
    loop = Loop(
        name=PROPOSAL_LOOP_NAME,
        body=[make_propose_amount_stage(step=30), make_review_amount_stage(minimum=60), confirm],
        continue_when=needs_revision_continue_when,
        max_iterations=5,
    )

    ctx = RunContext(
        state=InMemoryStateStore(initial=loop_demo_empty_state()),
        checkpoint_handler=handler,
        hooks=LifecycleHooks(before_loop_iteration=lambda name, i: print(f"  --- {name} 第 {i + 1} 轮 ---")),
    )
    outputs = loop.run(ctx, {})
    print(f"结果: {outputs}")

    # 第 1 轮:金额 30,AI 判否(< 60),Loop 短路——人工这一轮根本不会被问到。
    # 第 2 轮:金额 60,AI 判过,轮到人工;人工第一次判否 -> 继续第 3 轮。
    # 第 3 轮:金额 90,AI 判过,人工第二次判过 -> 结束。
    assert calls["human_asked"] == 2
    assert outputs["_loop"]["iterations"] == 3
    assert ctx.state.get("proposal.amount") == 90
    print("\n断言通过:AI 判否的那一轮,人工完全没有被打扰过(只被问了 2 次而不是 3 次)。")


if __name__ == "__main__":
    demo_standalone()
    demo_inside_loop()
