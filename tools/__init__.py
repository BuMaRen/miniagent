"""工具系统。

把普通 Python 函数变成可被 LLM 调用的工具:从函数签名/docstring 自动生成
schema、统一注册、安全执行。Skill(agent/skill.py)就是若干这样的工具的集合。

    ToolSchema, schema_from_func —— 工具描述与自动生成
    ToolRegistry                 —— 工具注册表
    ToolExecutor                 —— 工具调用的安全执行
"""

from tools.schema import ToolSchema
from tools.registry import ToolRegistry, tool
from tools.executor import ToolExecutor

__all__ = ["ToolSchema", "ToolRegistry", "tool", "ToolExecutor"]
