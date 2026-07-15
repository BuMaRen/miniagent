"""Workflow —— 由 Node 组成的完整流程(docs/framework-design.md §7)。

Workflow 是场景方最终交给引擎运行的对象:一串按顺序执行的顶层节点
(每个节点可以是 Stage,也可以是 Sequence/Loop/ForEach/Checkpoint 等原语的嵌套)。
引擎负责按序驱动它们,并在节点之间通过 RunContext 传递输出与共享状态。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from engine.stage import Node
from engine.context import RunContext


@dataclass
class Workflow:
    """一个可执行的工作流。

    Attributes:
        name:  工作流名称(如 "novel_generation")。
        nodes: 顶层节点序列,按顺序执行。
        state_schema: 该场景的 State Schema(见 state/schema.py),用于初始化/校验共享状态。
    """

    name: str
    nodes: list[Node] = field(default_factory=list)
    state_schema: Any | None = None

    def run(self, ctx: RunContext, inputs: dict[str, Any]) -> dict[str, Any]:
        """从上到下执行所有顶层节点。

        约定:上一个节点的 outputs 作为下一个节点的 inputs 传入(节点也可
        选择只通过 ctx.state 通信)。返回最后一个节点的 outputs。
        """
        # TODO:
        #   1. (可选)用 self.state_schema 初始化/校验 ctx.state。
        #   2. 依次对每个 node 调用 node.run(ctx, inputs),把返回值作为下一个 inputs。
        #   3. 支持从 Checkpoint 恢复:若 ctx 携带恢复点信息,则跳到对应节点继续。
        #   4. 返回最终 outputs。
        raise NotImplementedError

    @classmethod
    def from_spec(cls, spec: dict[str, Any], registry: "NodeRegistry") -> "Workflow":
        """从声明式定义(如 §7 的 YAML 结构)构建 Workflow。

        spec 用 sequence / loop / foreach / checkpoint 等关键字描述结构,
        registry 负责把关键字与具体 Stage 名映射成真正的 Node 实例。
        这是"场景方只写配置即可拼流程"的入口。
        """
        # TODO: 递归解析 spec,借助 registry 实例化每个节点。
        raise NotImplementedError


class NodeRegistry:
    """名称 -> Node 的登记表,供 Workflow.from_spec 解析声明式定义时查找。"""

    def __init__(self) -> None:
        self._nodes: dict[str, Node] = {}

    def register(self, node: Node) -> None:
        """登记一个具名节点(通常是 Stage)。"""
        # TODO: self._nodes[node.name] = node
        raise NotImplementedError

    def get(self, name: str) -> Node:
        """按名取回节点,缺失时应给出清晰错误。"""
        raise NotImplementedError
