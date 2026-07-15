"""Sequence —— 顺序执行原语(docs/framework-design.md §6.1)。

A -> B -> C:上一个节点的输出流入下一个节点的输入(也可只经由共享状态通信)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from engine.stage import Node
from engine.context import RunContext


@dataclass
class Sequence:
    """按顺序执行一串子节点。"""

    name: str
    nodes: list[Node] = field(default_factory=list)

    def run(self, ctx: RunContext, inputs: dict[str, Any]) -> dict[str, Any]:
        # TODO: 依次执行 self.nodes,把每个节点的 outputs 作为下一个的 inputs;
        #       返回最后一个节点的 outputs。空序列时原样返回 inputs。
        raise NotImplementedError
