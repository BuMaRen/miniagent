"""ToolSet —— 一组赋予 Agent 特定能力的工具(docs/framework-design.md §4)。

ToolSet 本质上只是数据:一批 (tool_func, ToolSchema)。它不需要实例化成 Agent,
可以被组合(一个 Agent 加载多个 ToolSet),语义清晰(ToolSet 是能力,Agent 是执行者)。
这是场景方二次开发的主要产出物——为每个 Stage 开发/挑选合适的 ToolSet。

注意:这里的 ToolSet 与 Claude/OpenAI 的 "Skill"(磁盘目录 + 元数据、供模型运行时
自主发现/渐进式加载)不是同一层概念。ToolSet 只是代码装配期显示挂载给 Agent 的一组
function-calling 工具,不涉及运行时的目录扫描或模型自主发现。 
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from tools.schema import ToolSchema, schema_from_func

# 一个工具 = 可调用函数 + 其 schema。
Tool = tuple[Callable[..., object], ToolSchema]


@dataclass
class ToolSet:
    """一组相关工具的集合。

    Attributes:
        name:  工具集名(如 "chapter_writing_toolset"),用于挂载映射与日志。
        tools: 该工具集包含的工具列表。
    """

    name: str
    tools: list[Tool] = field(default_factory=list)

    @classmethod
    def from_funcs(cls, name: str, funcs: list[Callable[..., object]]) -> "ToolSet":
        """便捷构造:从普通函数列表自动生成 schema 组装成 ToolSet。

        依赖 tools.schema.schema_from_func 从函数签名/docstring 推断 ToolSchema。
        """
        return cls(name, [(f, schema_from_func(f)) for f in funcs])

    def tool_names(self) -> list[str]:
        """返回该 ToolSet 暴露的所有工具名,便于校验重名冲突。"""
        return [schema.name for _, schema in self.tools]


class ToolSetRegistry:
    """"工具集名 -> ToolSet"的登记表,与 tools.registry.ToolRegistry 同构。

    注意两张表管的不是一回事:ToolRegistry 管的是**单个工具**(挂在某个 Agent 上、
    供 LLM 调用),这里管的是**工具集**(装配期的挂载单位)。有这张表,stages.yaml
    里才能用一个裸字符串挂载能力(`tools: [research]`)——ToolSet 本身是对象,
    YAML 里只写得下它的名字。
    """

    # 约定俗成的后缀:场景方通常把工具集命名成 "research_toolset",但在 YAML 里
    # 逐个写 "_toolset" 只是噪音,所以 get 允许省略它。
    _NAME_SUFFIX = "_toolset"

    def __init__(self) -> None:
        self._toolsets: dict[str, ToolSet] = {}

    def register(self, toolset: ToolSet) -> bool:
        """登记一个工具集(key 取 toolset.name);遇到重名返回 False,否则返回 True。"""
        if toolset.name in self._toolsets:
            return False
        self._toolsets[toolset.name] = toolset
        return True

    def unregister(self, name: str) -> None:
        """移除一个工具集(重名登记前先卸载,或热替换时会用到)。"""
        self._toolsets.pop(name, None)

    def names(self) -> list[str]:
        """已登记的全部工具集名(排序后),用于报错时列出候选。"""
        return sorted(self._toolsets)

    def get(self, name: str) -> ToolSet:
        """按名取回工具集;精确匹配不到时再试 `name + "_toolset"`。"""
        for key in (name, f"{name}{self._NAME_SUFFIX}"):
            if key in self._toolsets:
                return self._toolsets[key]
        known = ", ".join(self.names()) or "<空>"
        raise KeyError(f"工具集 {name!r} 未注册;已登记: {known}")


# 全局默认注册表,供场景方登记自己的 ToolSet、engine/spec.py 按名挂载时共享。
default_registry = ToolSetRegistry()


def register(toolset: ToolSet) -> bool:
    """把一个工具集登记进 default_registry(等价于 default_registry.register)。"""
    return default_registry.register(toolset)
