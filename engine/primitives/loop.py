"""Loop —— Critic-Reviser 循环原语(docs/framework-design.md §6.2)。

通用的"生成 -> 评审 -> 修订 -> 直到达标或超限退出"。退出条件由 critic 的输出
决定,引擎不假设"什么叫合格"。这个原语被设计为独立、可复用:小说场景里它被
实例化两次(大纲评审、章节审校),换场景可直接复用。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from engine.stage import Node
from engine.context import CheckpointRequest, RunContext


class OnExceed(str, Enum):
    """达到 max_iterations 仍未通过时的策略。"""

    ACCEPT_LAST = "accept_last_version"  # 接受最后一版,继续后续流程
    ESCALATE_TO_CHECKPOINT = "escalate_to_checkpoint"  # 升级为人工断点介入
    RAISE = "raise"  # 直接报错终止(禁止上层无限重试)


# critic 节点约定输出的结构:{"passed": bool, "feedback": str}
CRITIC_PASSED_KEY = "passed"
CRITIC_FEEDBACK_KEY = "feedback"


@dataclass
class Loop:
    """评审-修订循环。

    Attributes:
        name:           循环名称(用于日志/断点定位)。
        producer:       产出待评审内容(首轮执行)。
        critic:         评审节点,输出 {passed: bool, feedback: str}。
        reviser:        依据 feedback 修订 producer 的输出;可与 producer 是同一个节点。
        max_iterations: 最大迭代次数,防止死循环。
        on_exceed:      超限策略。
    """

    name: str
    producer: Node
    critic: Node
    reviser: Node
    max_iterations: int = 3
    on_exceed: OnExceed = OnExceed.ESCALATE_TO_CHECKPOINT

    def run(self, ctx: RunContext, inputs: dict[str, Any]) -> dict[str, Any]:
        # 实现循环控制流
        #   1. current = producer.run(ctx, inputs)
        #   2. for i in range(max_iterations):
        #        verdict = critic.run(ctx, current)
        #        emit after_loop_iteration(name, i, verdict[passed])
        #        if verdict[passed]: return current
        #        current = reviser.run(ctx, {**current, "feedback": verdict[feedback]})
        #   3. 循环结束仍未通过 -> 按 on_exceed 处理:
        #        ACCEPT_LAST            -> return current
        #        ESCALATE_TO_CHECKPOINT -> 调用 ctx.checkpoint_handler 请求人工裁决
        #        RAISE                  -> raise LoopExceededError
        current = self.producer.run(ctx, inputs)
        verdict = self.critic.run(ctx, current)
        if verdict[CRITIC_PASSED_KEY]:
            return current
        for i in range(self.max_iterations):
            if ctx.hooks and ctx.hooks.before_loop_iteration:
                ctx.hooks.before_loop_iteration(self.name, i)
            current = self.reviser.run(
                ctx, {**current, "feedback": verdict[CRITIC_FEEDBACK_KEY]}
            )
            verdict = self.critic.run(ctx, current)
            if ctx.hooks and ctx.hooks.after_loop_iteration:
                ctx.hooks.after_loop_iteration(self.name, i, verdict[CRITIC_PASSED_KEY])
            if verdict[CRITIC_PASSED_KEY]:
                return current
        # 循环结束仍未通过 -> 按 on_exceed 处理
        if self.on_exceed == OnExceed.ACCEPT_LAST:
            return current
        elif self.on_exceed == OnExceed.ESCALATE_TO_CHECKPOINT:
            if ctx.checkpoint_handler is None:
                raise RuntimeError("Loop 超限,但 RunContext 未配置 checkpoint_handler")
            # 升级为人工裁决:把"最后一版草稿"作为 context 素材交给人参考,
            # 由 handler 返回人工敲定的最终产出。
            request = CheckpointRequest(
                name=self.name,
                prompt=f"Loop {self.name} 超过 max_iterations={self.max_iterations} 仍未通过,请人工裁决。",
                context=current,
            )
            return ctx.checkpoint_handler(request)
        elif self.on_exceed == OnExceed.RAISE:
            raise LoopExceededError(
                f"Loop {self.name} 超过 max_iterations={self.max_iterations} 且未通过"
            )
        else:
            raise ValueError(f"未知的 on_exceed 策略: {self.on_exceed}")


class LoopExceededError(RuntimeError):
    """Loop 超过 max_iterations 且策略为 RAISE 时抛出。"""
