"""Breaker —— 提前终止 Loop/ForEach 的原语。

和 Continuer(见 engine/primitives/continuer.py)的分工:两者都是放进 Loop/
ForEach body 里的普通 Node,自带一个 `predicate(ctx, inputs) -> bool`,互不
知晓对方存在。Breaker 为真时立刻终止**最近的**外层 Loop/ForEach——对 Loop
相当于"提前放行,接受当前结果结束循环"(区别于 max_iterations 耗尽触发的
on_exceed 三选一,这是内容触发而非轮次耗尽触发);对 ForEach 相当于 Python 的
`break`,停止处理剩余 items。Continuer 只对 Loop 生效,为真时相当于 Python 的
`continue`——跳过本轮 body 剩下的节点,从 body[0] 重开下一轮。

不支持"指定中断到哪一层"(labeled break):嵌套 Loop/ForEach 时,`LoopBreak` 天然
只被 Python 异常传播路径上最近的 try/except 捕获,已经就是"只断最近一层"。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from engine.context import RunContext

BreakerPredicate = Callable[["RunContext", dict[str, Any]], bool]


class LoopBreak(Exception):
    """predicate 为真时抛出,携带触发时的 outputs,由最近的 Loop/ForEach 捕获吸收。"""

    def __init__(self, name: str, outputs: dict[str, Any]) -> None:
        super().__init__(f"break requested by {name!r}")
        self.name = name
        self.outputs = outputs


@dataclass
class Breaker:
    """放进 Loop/ForEach body 里的"断路器":predicate 为真则中断最近的外层循环。

    Attributes:
        name:      标识名(用于日志/异常定位)。
        predicate: (ctx, inputs) -> bool,为真则触发中断。
    """

    name: str
    predicate: BreakerPredicate

    def run(self, ctx: RunContext, inputs: dict[str, Any]) -> dict[str, Any]:
        if self.predicate(ctx, inputs):
            raise LoopBreak(self.name, inputs)
        return inputs  # 不满足条件时纯透传,不碰状态
