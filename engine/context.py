"""RunContext —— 一次工作流运行贯穿始终的执行上下文。

它把"运行期需要共享给每个节点的东西"聚拢在一起:共享状态、遇到 Checkpoint
时怎么暂停/恢复、运行配置、以及可选的生命周期 hook。节点之间不直接互相引用,
一切共享都经由 RunContext,保证节点可独立测试。
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Callable

from state.store import StateStore

@dataclass(frozen=True)
class CheckpointRequest:
    """引擎向外部发起的一次"求人工输入"请求 —— CheckpointHandler 的唯一入参。

    只携带"为向人/外部系统征集输入所必需"的信息;刻意不含 RunContext /
    StateStore / config —— 从类型上就保证 handler 碰不到、也改不了引擎运行时状态。
    也刻意不含 schema:handler 是场景方实现的业务代码,只管"收集输入",契约校验
    是引擎(Checkpoint)的事,不该由被校验方自己盖章。

    Attributes:
        name:    断点/升级点名称,用于路由、展示与日志关联。
        prompt:  给人看的提示文案(可选)。
        context: 供人参考的运行时快照(只读,可选),如待裁决的草稿、上一轮
                 评审意见。它是"给人看的素材",不是让 handler 回写状态的通道。
                 构造时即深拷贝一份持有,与调用方原件彻底隔离——handler 就算
                 原地改了 context 里的可变对象,也波及不到引擎侧的原始数据。
    """

    name: str
    prompt: str | None = None
    context: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        # frozen=True 只冻结"字段绑定",管不到 context 这个 dict 内部的可变内容;
        # 在此深拷贝,把"只读"从口头约定变成机制保证。frozen 下不能直接赋值,
        # 需借 object.__setattr__ 绕过冻结(dataclass 后处理的标准写法)。
        if self.context is not None:
            object.__setattr__(self, "context", deepcopy(self.context))


# CheckpointHandler —— "收集一次外部(人工)输入"的回调,职责单一:
#   接到 CheckpointRequest,(阻塞)向人/外部系统征集输入,返回一份 dict。
#   它**只**做业务侧的"收集"这一件事:
#     · 不做校验              —— 返回值是否合法由 Checkpoint 用 schema 强制;
#     · 不接触 RunContext/State —— 拿不到,自然改不动运行时状态;
#     · 不决定控制流           —— 返回即"继续"。handler 是必需的(见
#       engine.primitives.checkpoint 模块 docstring);它若想"现在不答、留到以后
#       再说",直接在内部抛异常即可,会被 Workflow.run 的通用失败路径接住并允许
#       之后续跑,不需要靠专门的"暂停"返回值表达。
#   返回的 dict 怎么用(合并进 inputs / 作为节点产出)由调用方决定,与 handler 无关。
# 默认实现可以是命令行交互;场景/宿主可替换为 Web 表单、消息队列、审批系统等。
CheckpointHandler = Callable[[CheckpointRequest], dict[str, Any]]


@dataclass
class LifecycleHooks:
    """生命周期扩展点(全部可选)。

    引擎在关键节点回调这些函数,便于接入日志、进度上报、成本统计、
    人工审阅注入等,而无需改动引擎本体。
    """

    before_stage: Callable[[str, dict[str, Any]], None] | None = None
    after_stage: Callable[[str, dict[str, Any]], None] | None = None
    # loop 指的是 workflow 的 loop 而不是 Agent 中处理 ToolCall 的那层循环
    before_loop_iteration: Callable[[str, int], None] | None = None
    after_loop_iteration: Callable[[str, int, bool], None] | None = None
    on_checkpoint: Callable[[str], None] | None = None


@dataclass(frozen=True)
class ResumePoint:
    """从某次未预期的失败恢复运行所需的全部信息。

    顶层节点抛出未捕获异常时 Workflow.run 会包装成 WorkflowFailure(见
    engine/workflow.py)冒泡给宿主;宿主据此持久化后,下次运行时构造一个
    ResumePoint 塞进新的 RunContext,再次调用 Workflow.run 即可跳过已成功的前序
    节点、只从失败的这个节点重跑,而非从头重跑整个 workflow。Checkpoint 缺
    handler(或 handler 自己选择暂缓)时抛出的异常同样走这条路径——Checkpoint
    不再有专属的暂停/恢复机制(见 engine.primitives.checkpoint 模块 docstring)。

    Attributes:
        node_index: 顶层节点游标——Workflow.run 从该索引处的节点重新开始执行,
                    从而跳过已完成的前序顶层节点(避免重复调用其 executor)。
        inputs:     失败时正流入该节点的 inputs;恢复时以它作为续跑的起始输入。
    """

    node_index: int
    inputs: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunContext:
    """工作流运行上下文。

    Attributes:
        state:              共享状态存储(State Store 接口的某个实例)。
        checkpoint_handler: 处理人工断点的回调。
        config:             运行配置(如各 Loop 的默认 max_iterations、模型参数等)。
        hooks:              生命周期钩子集合(before/after stage、loop 迭代等),可选。
        trace:              运行轨迹记录器,用于可观测性/调试,可选。
        resume:             失败续跑信息(见 ResumePoint);非 None 时表示"这是一次
                            续跑",Workflow.run 据此定位起点、以 resume.inputs 作为
                            起始输入,跳过已成功的前序顶层节点。
    """

    state: StateStore
    checkpoint_handler: CheckpointHandler | None = None
    config: dict[str, Any] = field(default_factory=dict)
    hooks: LifecycleHooks | None = None
    trace: list[dict[str, Any]] = field(default_factory=list)
    resume: "ResumePoint | None" = None

    def emit(self, event: str, payload: dict[str, Any]) -> None:
        """记录一条运行事件到 trace,供可观测性/调试使用。

        每条记录形如 ``{"event": ..., "payload": ...}``。payload 深拷贝后持有,
        与调用方原件隔离——之后节点再改动传入的 dict,也不会回溯篡改已落盘的轨迹。

        Args:
            event:   事件名(如 "stage.start"、"loop.iteration"),用于过滤与展示。
            payload: 事件附带的结构化数据。
        """
        self.trace.append({"event": event, "payload": deepcopy(payload)})
