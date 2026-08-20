"""ToolSet —— 一组赋予 Agent 特定能力的工具。

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

from bumaren_agent_workflow.tools.schema import ToolSchema, schema_from_func

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
