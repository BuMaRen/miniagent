"""Workflow —— 由 Node 组成的完整流程。

Workflow 是场景方最终交给引擎运行的对象:一串按顺序执行的顶层节点
(每个节点可以是 Stage,也可以是 Sequence/Loop/ForEach/Checkpoint 等原语的嵌套)。
引擎负责按序驱动它们,并在节点之间通过 RunContext 传递输出与共享状态。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from copy import deepcopy

from bumaren_agent_workflow.engine.stage import Node
from bumaren_agent_workflow.engine.context import RunContext


class WorkflowFailure(Exception):
    """顶层节点抛出未捕获异常时的封装,携带续跑所需的游标与 inputs。

    宿主捕获后通常会持久化 (node_index, inputs),下次运行时构造一个
    ``ResumePoint(node_index=..., inputs=...)`` 并塞进新的 RunContext 再次调用
    Workflow.run——即可跳过已成功的前序顶层节点,只从失败的这个节点起重跑,而不必
    从头重跑整个 workflow。Checkpoint 缺 handler(或 handler 自己选择暂缓,见
    engine.primitives.checkpoint 模块 docstring)时抛出的异常也走这同一条路径,
    不再有专属的暂停机制。

    node_index / inputs 在构造时即已知(由 Workflow.run 在捕获处直接算出)。
    原始异常挂在 __cause__ 上(见 ``raise failure from err``),诊断信息不丢失。
    """

    def __init__(self, node_name: str, node_index: int, inputs: dict[str, Any]) -> None:
        super().__init__(f"workflow failed at node {node_name!r} (index {node_index})")
        self.node_name = node_name
        self.node_index = node_index
        self.inputs = inputs


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
        # 顶层驱动:本质与 Sequence 相同(上一个 outputs 作为下一个 inputs),
        # 额外承担"整段运行"的可观测性收尾与 Checkpoint 续跑。
        #
        # 说明:
        #   · state_schema 初始化/校验:ctx.state 由调用方构造并注入(恢复场景下
        #     可能已从快照 load 过),此处不擅自清空重建;待 StateSchema.validate
        #     落地后可在此加一道可选校验。(本次按要求略过)
        #   · 续跑(失败重试):若 ctx.resume 非 None,说明这是一次恢复运行——从
        #     resume.node_index 处的顶层节点开始,以 resume.inputs 作为起始输入,
        #     跳过已完成的前序顶层节点(避免重复调用它们的 executor)。节点本身按
        #     正常逻辑重新执行。
        #   · 局限:游标只到"顶层节点"粒度。若失败点嵌套在 Sequence/Loop/ForEach
        #     内部,node_index 指向的是那个容器,恢复会重跑该容器内失败点之前的
        #     兄弟节点(容器整体重新执行)。真正的嵌套续跑需把游标贯穿到各容器
        #     原语,属后续工作。
        start = 0
        outputs = inputs
        if ctx.resume is not None:
            start = ctx.resume.node_index
            outputs = ctx.resume.inputs

        ctx.emit(
            "workflow.start",
            {"workflow": self.name, "inputs": outputs, "resume_from": start},
        )

        for i in range(start, len(self.nodes)):
            node = self.nodes[i]
            try:
                outputs = node.run(ctx, outputs)
            except Exception as err:
                # 未预期的失败(网络抖动、Provider 报错、契约解析失败、Checkpoint
                # 缺 handler……):把"游标 + 流入的 inputs"封进 WorkflowFailure 冒泡
                # 给宿主。宿主据此持久化后,下次运行可从 node_index 处(即失败
                # 的这个节点本身,而非其后)重新开始,从而复用前面已成功节点的产出,
                # 不必从头重跑整个 workflow。原始异常通过 `raise ... from err` 保留
                # 在 __cause__ 上,不丢失诊断信息。
                failure = WorkflowFailure(node_name=node.name, node_index=i, inputs=deepcopy(outputs))
                ctx.emit(
                    "workflow.failed",
                    {
                        "workflow": self.name,
                        "node": node.name,
                        "node_index": i,
                        "error": repr(err),
                    },
                )
                raise failure from err

        ctx.emit("workflow.end", {"workflow": self.name, "outputs": outputs})
        return outputs
