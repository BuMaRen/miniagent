"""控制流原语。

这些原语足以组合出目前设想的所有流程形态,且都实现 engine.stage.Node 协议,
因此可以任意嵌套(例如 ForEach 的 body 是一个 Loop)。它们全部场景无关。

    Sequence   —— 顺序执行子节点
    Loop       —— 迭代:反复跑一串节点,直到某一轮完整跑完都没人要求重来或超限
    ForEach    —— 对列表中每个元素重复执行子流程
    Checkpoint —— 同步向外部(人工)索要输入的断点
    Breaker    —— 放进 Loop/ForEach body 里的断路器,predicate 为真则提前终止
                  最近的外层 Loop/ForEach(见 breaker.py 模块 docstring)
    Continuer  —— 放进 Loop body 里的继续器,predicate 为真则跳过本轮剩余节点、
                  从 body[0] 重开下一轮,与 Breaker 对称(见 continuer.py 模块
                  docstring)
"""

from bumaren_agent_workflow.engine.primitives.sequence import Sequence
from bumaren_agent_workflow.engine.primitives.loop import Loop, OnExceed
from bumaren_agent_workflow.engine.primitives.foreach import ForEach
from bumaren_agent_workflow.engine.primitives.checkpoint import Checkpoint
from bumaren_agent_workflow.engine.primitives.breaker import Breaker, LoopBreak
from bumaren_agent_workflow.engine.primitives.continuer import Continuer, LoopContinue

__all__ = [
    "Sequence",
    "Loop",
    "OnExceed",
    "ForEach",
    "Checkpoint",
    "Breaker",
    "LoopBreak",
    "Continuer",
    "LoopContinue",
]
