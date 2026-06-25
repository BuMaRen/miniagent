# ToolRegistry：工具的注册与查找中心。
#
# 功能：
#   - register(name, func, schema)  注册一个工具（名称、可调用函数、Schema）
#   - get(name) -> (func, schema)   按名称查找工具
#   - schemas() -> list[ToolSchema] 返回所有注册工具的 Schema 列表，供 LLM 调用时传入
#
# 提供 @tool 装饰器（在此文件或 __init__.py 中定义）：
#   - 用法：@registry.tool 或 @tool（全局默认注册表）
#   - 自动调用 schema_from_func 生成 Schema 并注册
#   - 装饰后函数行为不变，仍可直接调用
#
# 注意：
#   - 工具名重复注册时应抛出明确异常，避免静默覆盖

from dataclasses import dataclass

from tools.schema import ToolSchema


@dataclass
class FuncTuple:
    func: callable
    schema: ToolSchema


@dataclass
class ToolRegistry:

    registry: dict

    def register(self, name: str, func: callable, schema: ToolSchema):
        """
        注册一个工具。
        """
        if name in self.registry:
            raise ValueError(f"Tool '{name}' is already registered.")
        self.registry[name] = FuncTuple(func, schema)

    def get(self, name: str):
        """
        按名称查找工具，返回 (func, schema)。
        """
        if name not in self.registry:
            raise KeyError(f"Tool '{name}' is not registered.")
        func_tuple = self.registry[name]
        return func_tuple.func, func_tuple.schema

    def schemas(self):
        """
        返回所有注册工具的 Schema 列表。
        """
        return [func_tuple.schema for func_tuple in self.registry.values()]
