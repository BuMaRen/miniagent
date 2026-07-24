"""Workflow —— 由 Node 组成的完整流程(docs/framework-design.md §7)。

Workflow 是场景方最终交给引擎运行的对象:一串按顺序执行的顶层节点
(每个节点可以是 Stage,也可以是 Sequence/Loop/ForEach/Checkpoint 等原语的嵌套)。
引擎负责按序驱动它们,并在节点之间通过 RunContext 传递输出与共享状态。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from copy import deepcopy

from engine.stage import Node
from engine.context import RunContext
from engine.primitives.checkpoint import Checkpoint, CheckpointPause
from engine.primitives.foreach import ForEach
from engine.primitives.loop import Loop, OnExceed
from engine.primitives.sequence import Sequence


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
        #   · Checkpoint 续跑:若 ctx.resume 非 None,说明这是一次恢复运行——从
        #     resume.node_index 处的顶层节点开始,以 resume.inputs 作为起始输入,
        #     跳过已完成的前序顶层节点(避免重复调用它们的 executor)。断点处的
        #     人工输入由对应 Checkpoint 从 ctx.resume 认领。
        #   · 局限:游标只到"顶层节点"粒度。若 Checkpoint 嵌套在 Sequence/Loop/
        #     ForEach 内部,node_index 指向的是那个容器,恢复会重跑该容器内断点
        #     之前的兄弟节点(断点本身仍能按名认领输入、不会二次暂停)。真正的
        #     嵌套续跑需把游标贯穿到各容器原语,属后续工作。
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
            try:
                outputs = self.nodes[i].run(ctx, outputs)
            except CheckpointPause as pause:
                # Checkpoint 不知道自己在顶层序列里的位置;在此回填游标与当前流入
                # inputs,宿主据此(连同 state 快照)构造 ResumePoint 以便日后续跑。
                pause.node_index = i
                pause.inputs = deepcopy(outputs)
                ctx.emit(
                    "workflow.paused",
                    {
                        "workflow": self.name,
                        "checkpoint": pause.checkpoint_name,
                        "node_index": i,
                    },
                )
                raise

        ctx.emit("workflow.end", {"workflow": self.name, "outputs": outputs})
        return outputs

    @classmethod
    def from_spec(cls, spec: dict[str, Any], registry: "NodeRegistry") -> "Workflow":
        """从声明式定义(如 §7 的 YAML 结构)构建 Workflow。

        spec 用 sequence / loop / foreach / checkpoint 等关键字描述结构,
        registry 负责把关键字与具体 Stage 名映射成真正的 Node 实例。
        这是"场景方只写配置即可拼流程"的入口。

        期望结构(见 §7):顶层是 {workflow, state_schema, stages: [...]},其中
        stages 每一项要么是一个已登记 Stage 的名字(str),要么是单键 dict —— 键
        是原语关键字(sequence/loop/foreach/checkpoint/stage),值描述其内容。原语
        可任意嵌套。

        state_schema 原样透传(可能是场景方已解析好的 StateSchema 实例,也可能是
        None);把字符串引用解析成具体 schema 不属本方法职责,由调用方在传入前完成。
        """
        raw_stages = spec.get("stages", [])
        nodes = [
            cls._build_node(raw, registry, str(i))
            for i, raw in enumerate(raw_stages)
        ]
        return cls(
            name=spec.get("workflow", "workflow"),
            nodes=nodes,
            state_schema=spec.get("state_schema"),
        )

    # -- from_spec 的递归解析辅助 ------------------------------------------------
    # path 是一条 dot-free 的定位串(如 "1_0"),用途有二:出错时定位、以及为未显式
    # 命名的原语生成确定性名字。刻意不含点号——ForEach 会用 name 拼出游标状态路径
    # (点分寻址),名字里带点会破坏寻址。

    @classmethod
    def _build_node(cls, raw: Any, registry: "NodeRegistry", path: str) -> Node:
        """把一条节点定义(str 或单键 dict)解析成 Node。"""
        # 裸字符串 = 直接引用一个已登记的 Stage。
        if isinstance(raw, str):
            return registry.get(raw)
        if not isinstance(raw, dict) or len(raw) != 1:
            raise ValueError(
                f"节点定义 @ {path} 须为 Stage 名(str)或单键 dict,得到: {raw!r}"
            )
        (kind, body), = raw.items()
        builder = {
            "stage": lambda: registry.get(body),
            "sequence": lambda: cls._build_sequence(body, registry, path),
            "loop": lambda: cls._build_loop(body, registry, path),
            "foreach": lambda: cls._build_foreach(body, registry, path),
            "checkpoint": lambda: cls._build_checkpoint(body, path),
        }.get(kind)
        if builder is None:
            raise ValueError(f"未知的原语关键字 @ {path}: {kind!r}")
        return builder()

    @classmethod
    def _build_sequence(
        cls, body: Any, registry: "NodeRegistry", path: str
    ) -> Sequence:
        if not isinstance(body, list):
            raise ValueError(f"sequence @ {path} 的值须为节点列表,得到: {body!r}")
        nodes = [
            cls._build_node(child, registry, f"{path}_{i}")
            for i, child in enumerate(body)
        ]
        return Sequence(name=f"sequence_{path}", nodes=nodes)

    @classmethod
    def _build_loop(cls, body: Any, registry: "NodeRegistry", path: str) -> Loop:
        if not isinstance(body, dict):
            raise ValueError(f"loop @ {path} 的值须为 dict,得到: {body!r}")
        for key in ("producer", "critic", "reviser"):
            if key not in body:
                raise ValueError(f"loop @ {path} 缺少必填字段 {key!r}")
        kwargs: dict[str, Any] = {
            "name": body.get("name", f"loop_{path}"),
            "producer": cls._build_node(body["producer"], registry, f"{path}_producer"),
            "critic": cls._build_node(body["critic"], registry, f"{path}_critic"),
            "reviser": cls._build_node(body["reviser"], registry, f"{path}_reviser"),
        }
        if "max_iterations" in body:
            kwargs["max_iterations"] = body["max_iterations"]
        if "on_exceed" in body:
            # OnExceed 是 str Enum,直接按值构造;非法值会抛清晰的 ValueError。
            kwargs["on_exceed"] = OnExceed(body["on_exceed"])
        return Loop(**kwargs)

    @classmethod
    def _build_foreach(
        cls, body: Any, registry: "NodeRegistry", path: str
    ) -> ForEach:
        if not isinstance(body, dict):
            raise ValueError(f"foreach @ {path} 的值须为 dict,得到: {body!r}")
        for key in ("items_path", "body"):
            if key not in body:
                raise ValueError(f"foreach @ {path} 缺少必填字段 {key!r}")
        return ForEach(
            name=body.get("name", f"foreach_{path}"),
            items_path=body["items_path"],
            body=cls._build_node(body["body"], registry, f"{path}_body"),
            index_path=body.get("index_path"),
            item_path=body.get("item_path"),
        )

    @classmethod
    def _build_checkpoint(cls, body: Any, path: str) -> Checkpoint:
        # 两种写法:`checkpoint: <名字>`(str),或带 prompt/schema 的 dict。
        if isinstance(body, str):
            return Checkpoint(name=body)
        if isinstance(body, dict):
            if "name" not in body:
                raise ValueError(f"checkpoint @ {path} 缺少必填字段 'name'")
            return Checkpoint(
                name=body["name"],
                resume_input_schema=body.get("resume_input_schema"),
                prompt=body.get("prompt"),
            )
        raise ValueError(f"checkpoint @ {path} 的值须为名字(str)或 dict,得到: {body!r}")


class NodeRegistry:
    """名称 -> Node 的登记表,供 Workflow.from_spec 解析声明式定义时查找。"""

    def __init__(self) -> None:
        self._nodes: dict[str, Node] = {}

    def register(self, node: Node) -> None:
        """登记一个具名节点(通常是 Stage)。重名视为配置错误,直接报错而非静默覆盖。"""
        if node.name in self._nodes:
            raise ValueError(f"NodeRegistry: 节点名 {node.name!r} 重复登记")
        self._nodes[node.name] = node

    def get(self, name: str) -> Node:
        """按名取回节点,缺失时给出带"已登记清单"的清晰错误。"""
        try:
            return self._nodes[name]
        except KeyError:
            known = ", ".join(sorted(self._nodes)) or "<空>"
            raise KeyError(
                f"NodeRegistry 中找不到节点 {name!r};已登记: {known}"
            ) from None
