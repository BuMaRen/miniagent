"""RunContext —— 一次工作流运行贯穿始终的执行上下文。

它把"运行期需要共享给每个节点的东西"聚拢在一起:共享状态、遇到 Checkpoint
时怎么暂停/恢复、运行配置、以及可选的生命周期 hook。节点之间不直接互相引用,
一切共享都经由 RunContext,保证节点可独立测试。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from state.store import StateStore

# Checkpoint 处理器:引擎执行到断点时调用它,阻塞等待外部(人工)输入,
# 返回符合 resume_input_schema 的数据。默认实现可以是命令行交互;
# 场景/宿主可替换为 Web 表单、消息队列等(见 engine/primitives/checkpoint.py)。
CheckpointHandler = Callable[[str, Any], dict[str, Any]]


@dataclass
class LifecycleHooks:
    """生命周期扩展点(全部可选)。

    引擎在关键节点回调这些函数,便于接入日志、进度上报、成本统计、
    人工审阅注入等,而无需改动引擎本体。
    """

    before_stage: Callable[[str, dict[str, Any]], None] | None = None
    after_stage: Callable[[str, dict[str, Any]], None] | None = None
    before_loop_iteration: Callable[[str, int], None] | None = None
    after_loop_iteration: Callable[[str, int, bool], None] | None = None
    on_checkpoint: Callable[[str], None] | None = None


@dataclass
class RunContext:
    """工作流运行上下文。

    Attributes:
        state:              共享状态存储(State Store 接口的某个实例)。
        checkpoint_handler: 处理人工断点的回调。
        config:             运行配置(如各 Loop 的默认 max_iterations、模型参数等)。
        hooks:              生命周期钩子集合(before/after stage、loop 迭代等),可选。
        trace:              运行轨迹记录器,用于可观测性/调试,可选。
    """

    state: StateStore
    checkpoint_handler: CheckpointHandler | None = None
    config: dict[str, Any] = field(default_factory=dict)
    hooks: LifecycleHooks | None = None
    trace: list[dict[str, Any]] = field(default_factory=list)

    def emit(self, event: str, payload: dict[str, Any]) -> None:
        """记录一条运行事件到 trace,并转发给 hooks(若存在)。"""
        # TODO: 追加到 self.trace;若 self.hooks 有对应回调则调用。
        raise NotImplementedError
