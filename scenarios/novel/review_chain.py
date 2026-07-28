"""ReviewChain —— 本场景自定义的 Node:把若干 critic 串成一道多关卡评审。

**这是场景代码,不是引擎原语。** "多个 critic 依次把关"是一种评审*策略*,不是
Sequence/Loop/ForEach/Checkpoint 那样的控制流*形状*,所以它不该进
engine/primitives/。引擎在这件事上已经给够了:`Node` 是一个 Protocol(见
engine/stage.py),只要求 `name` + `run(ctx, inputs) -> outputs`——任何场景都能
自己造一个满足它的类型,直接塞进 Loop 的 critic 槽位 / Sequence 的 nodes /
ForEach 的 body,和内置原语平起平坐。

注意本类没有继承任何基类:Python 的 Protocol 是结构化(鸭子)类型,"实现了对应
的方法"即视作实现了 Node,无需显式继承。这正是场景方扩展引擎的推荐姿势——
不改引擎、不加原语,只补一个自己的 Node。

用途:小说场景要的是"AI critic 先挡掉明显问题,通过后再让人工把关",且人工
提出的意见要和 AI 的意见一样驱动 reviser 重写、下一轮重新走完整条链。把两个
critic 串起来即可,外层 Loop 完全不知道自己的 critic 内部还套了几层。

短路语义:前一个 critic 不通过就不再问后一个(不必拿一份 AI 都没过的草稿去
打扰人工);全部通过则返回最后一个 critic 的 verdict。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.context import RunContext
from engine.primitives.loop import (
    CRITIC_FEEDBACK_KEY,
    CRITIC_PASSED_KEY,
    CriticContractError,
)
from engine.stage import Node


@dataclass
class ReviewChain:
    """依次执行多个 critic,整体仍满足 Loop 的 critic 契约。

    Attributes:
        name:    链名称(用于日志定位,以及在 NodeRegistry 里被 workflow.yaml 按名引用)。
        critics: 依次执行的 critic 列表;每个都需满足 {"passed": bool, "feedback": str}
                 契约。它们收到的都是**同一份** inputs(被评审的内容本身),而不是
                 把上一个的 verdict 传给下一个——是并列的多道关卡,不是接力。
    """

    name: str
    critics: list[Node]

    def run(self, ctx: RunContext, inputs: dict[str, Any]) -> dict[str, Any]:
        verdict: dict[str, Any] = {}
        for critic in self.critics:
            verdict = critic.run(ctx, inputs)
            if CRITIC_PASSED_KEY not in verdict:
                raise CriticContractError(
                    f"critic {critic.name!r}(属于评审链 {self.name!r})的输出不满足契约:"
                    f"缺少 {CRITIC_PASSED_KEY} 字段,实际输出: {verdict}"
                )
            if not verdict[CRITIC_PASSED_KEY]:
                if CRITIC_FEEDBACK_KEY not in verdict:
                    raise CriticContractError(
                        f"critic {critic.name!r}(属于评审链 {self.name!r})的输出不满足契约:"
                        f"缺少 {CRITIC_FEEDBACK_KEY} 字段,实际输出: {verdict}"
                    )
                return verdict  # 短路:后面的 critic 不再问。
        return verdict
