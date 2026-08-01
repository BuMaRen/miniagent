"""Stage —— 最小执行单元(docs/framework-design.md §3)。

Stage 是一个"输入 -> 输出"的契约容器。它本身不关心"怎么产出输出",
只声明:谁来执行(executor)、需要从共享状态读哪些切片(reads)、会写哪些
切片(writes)。换一个 executor(例如换一个挂了不同 ToolSet 的 Agent),
同一个 Stage 定义就能在不同场景里做完全不同的事——这是场景可替换性的关键。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, Sequence, runtime_checkable

# 指向 State Store 中某个字段的路径,形如 "story_bible.characters"。
StatePath = str


@runtime_checkable
class Node(Protocol):
    """所有可执行节点的统一协议。这是抽象概念,Stage 只是其中一种具体实现。

    Stage 以及全部控制流原语(Sequence / Loop / ForEach / Checkpoint)都实现
    这个协议,因此可以任意嵌套组合(见 engine/primitives/)。

    类似于 Golang 的 interface,Node 只声明了一个 run() 方法,不关心具体实现。
    只要有一个对象具有 name 且实现了 run() 方法,就可以被当作 Node 使用,这就是 Python 的"鸭子类型"。
    """

    name: str

    def run(self, ctx: "RunContext", inputs: dict[str, Any]) -> dict[str, Any]:
        """执行本节点,返回输出字典。

        实现约定:
        - 只通过 ctx.state 读写共享状态,便于依赖分析与上下文切片。
        - 不应有隐藏的全局副作用,保证节点可组合、可测试。
        """
        ...


# 执行体:要么是一个 Agent(见 agent/agent.py),要么是一个普通可调用对象。
# 统一签名为 (ctx, inputs) -> outputs。
Executor = Callable[["RunContext", dict[str, Any]], dict[str, Any]]


class ExecutorRegistry:
    """名称 -> Executor 的登记表(与 tools/registry.py 的 ToolRegistry 对称)。

    为"把 Stage 构造下沉到框架"做准备:届时可以按名字从这里查到 Executor,
    结合声明式配置(reads/writes/schema...)组装出 Stage,而不必在场景侧
    (如 scenarios/novel/stages.py)一个个手写 build_xxx_stage 函数。
    """

    def __init__(self) -> None:
        self._executors: dict[str, Executor] = {}

    def register(self, name: str, fn: Executor) -> bool:
        """登记一个 executor;遇到重名返回 False,否则返回 True。"""
        if name in self._executors:
            return False
        self._executors[name] = fn
        return True

    def unregister(self, name: str) -> None:
        """移除一个 executor(重名登记前先卸载,或热替换时会用到)。"""
        self._executors.pop(name, None)

    def names(self) -> list[str]:
        """已登记的全部 executor 名(排序后),用于报错时列出候选。"""
        return sorted(self._executors)

    def get(self, name: str) -> Executor:
        """按名取回 executor,缺失时给出带候选清单的清晰错误。"""
        try:
            return self._executors[name]
        except KeyError:
            known = ", ".join(self.names()) or "<空>"
            raise KeyError(f"Executor '{name}' 未注册;已登记: {known}") from None


# 全局默认注册表,供场景侧用 @executor 装饰器登记。
default_registry = ExecutorRegistry()


def executor(func: Executor) -> Executor:
    """装饰器:把一个函数注册为 executor,登记到 default_registry。

    用法:
        @executor
        def input_parsing(ctx: RunContext, inputs: dict[str, Any]) -> dict[str, Any]:
            ...

    与 tools.registry.tool 对称:tool 面向 LLM 可调用的工具,executor 面向
    Stage 的执行体;两者都以函数名(func.__name__)作为登记 key。
    """
    default_registry.register(func.__name__, func)
    return func


@dataclass
class Stage:
    """一个具体的执行步骤。

    Attributes:
        name:          唯一名称,用于日志、ToolSet 挂载映射(见 §4/§7)。
        executor:      真正把 inputs 变成 outputs 的执行体(通常是 Agent)。
        input_schema:  输入契约(交给 state/schema.py 校验,可为 None 表示不校验)。
        output_schema: 输出契约。
        reads:         声明式:执行前需要注入的状态切片路径。
        writes:        声明式:执行后允许写回的状态切片路径。
    """

    name: str
    executor: Executor
    input_schema: Any | None = None
    output_schema: Any | None = None
    reads: Sequence[StatePath] = field(default_factory=tuple)
    writes: Sequence[StatePath] = field(default_factory=tuple)

    def run(self, ctx: "RunContext", inputs: dict[str, Any]) -> dict[str, Any]:
        # 实现执行流程
        #   1. 若 input_schema 存在,校验 inputs。
        #   2. 通过 ctx.state.slice(self.reads) 取相关状态切片,合并进 inputs。
        #   3. 触发生命周期 hook(before_stage),调用 self.executor(ctx, inputs)。
        #   4. 若 output_schema 存在,校验 outputs。
        #   5. 依据 self.writes 把 outputs 中对应字段写回 ctx.state。
        #   6. 触发 after_stage hook,返回 outputs。
        if self.input_schema is not None:
            self.input_schema.validate(inputs)
        if ctx.hooks and ctx.hooks.before_stage:
            ctx.hooks.before_stage(self.name, inputs)
        if self.reads:
            state_slice = ctx.state.slice(self.reads)
            inputs.update({"state": state_slice})

        outputs = self.executor(ctx, inputs)

        if self.output_schema is not None:
            self.output_schema.validate(outputs)
        if self.writes:
            for path in self.writes:
                if path in outputs:
                    ctx.state.patch(path, outputs[path])
        if ctx.hooks and ctx.hooks.after_stage:
            ctx.hooks.after_stage(self.name, outputs)
        return outputs


# 避免循环导入:仅类型检查时引入 RunContext
from typing import TYPE_CHECKING  # noqa: E402

if TYPE_CHECKING:
    from engine.context import RunContext
