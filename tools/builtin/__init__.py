# 内置工具集的入口，提供所有 Agent 共用的基础工具。
#
# 每个工具文件导出一个工具列表（如 fs_tools），列表元素为 (func, schema) 元组。
# 调用方通过 ToolRegistry.register() 手动注册，以便明确控制哪些工具可用。
#
# 使用方式：
#   from tools.builtin.fs import fs_tools
#   for func, schema in fs_tools:
#       registry.register(schema.name, func, schema)
from .fs import fs_tools