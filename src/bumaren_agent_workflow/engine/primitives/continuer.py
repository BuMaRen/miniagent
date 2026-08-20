"""Continuer —— 与 Breaker 对称的"continue"信号原语。

Breaker 放进 Loop/ForEach body 里,predicate 为真时提前结束最近的外层循环
(相当于 Python 的 `break`)。Continuer 是它的对称面:放进 Loop 的 body 里,
predicate 为真时跳过本轮 body 剩下的节点,从 body[0] 直接重开下一轮(相当于
Python 的 `continue`)。

这取代了此前 Loop 自带的 `continue_when` 隐式协议——旧协议要求 body 里每个
节点跑完后引擎都自动拿它的 outputs 问一遍 continue_when,为了不被非决策节点
的输出误伤,只能靠"只有真正做判定的那个节点的输出里带这个字段,其它节点的
输出没有"这种隐式换算才能安全工作(见 engine/primitives/loop.py 的历史版本)。
现在"该不该重开一轮"收回成一个普通 Node,场景方自己决定放在 body 的哪个
位置、判定逻辑读什么状态——和 Breaker 放在哪里、判定什么完全是同一件事,
不需要两套心智模型。

只对 Loop 生效(ForEach 没有"重开当前项"这个概念,它的每一项本来就只跑一遍,
不像 Loop 的 body 需要反复对着同一份输入重跑)。

不支持"指定重开到哪一层"(labeled continue):嵌套 Loop 时,`LoopContinue`
天然只被 Python 异常传播路径上最近的 try/except 捕获,已经就是"只重开最近
一层"。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from bumaren_agent_workflow.engine.context import RunContext

ContinuerPredicate = Callable[["RunContext", dict[str, Any]], bool]


class LoopContinue(Exception):
    """predicate 为真时抛出,携带触发时的 outputs,由最近的 Loop 捕获,从 body[0] 重开下一轮。"""

    def __init__(self, name: str, outputs: dict[str, Any]) -> None:
        super().__init__(f"continue requested by {name!r}")
        self.name = name
        self.outputs = outputs


@dataclass
class Continuer:
    """放进 Loop body 里的"继续器":predicate 为真则跳过本轮剩余节点,从
    body[0] 重开下一轮,与 Breaker 对称(见模块 docstring)。

    Attributes:
        name:      标识名(用于日志/异常定位)。
        predicate: (ctx, inputs) -> bool,为真则触发重开。
    """

    name: str
    predicate: ContinuerPredicate

    def run(self, ctx: RunContext, inputs: dict[str, Any]) -> dict[str, Any]:
        if self.predicate(ctx, inputs):
            raise LoopContinue(self.name, inputs)
        return inputs  # 不满足条件时纯透传,不碰状态
