"""控制流原语(docs/framework-design.md §6)。

四个原语足以组合出目前设想的所有流程形态,且都实现 engine.stage.Node 协议,
因此可以任意嵌套(例如 ForEach 的 body 是一个 Loop)。它们全部场景无关。

    Sequence   —— 顺序执行子节点
    Loop       —— Critic-Reviser 循环:生成->评审->修订->直到达标或超限
    ForEach    —— 对列表中每个元素重复执行子流程
    Checkpoint —— 暂停等待外部(人工)输入的断点
"""

from engine.primitives.sequence import Sequence
from engine.primitives.loop import Loop
from engine.primitives.foreach import ForEach
from engine.primitives.checkpoint import Checkpoint

__all__ = ["Sequence", "Loop", "ForEach", "Checkpoint"]
