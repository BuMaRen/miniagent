# ToolRegistry：工具的注册与查找中心。
#
# 功能：
#   - register(name, func, schema)  注册一个工具（名称、可调用函数、Schema）
#   - get(name) -> (func, schema)   按名称查找工具
#   - schemas() -> list[ToolSchema] 返回所有注册工具的 Schema 列表，供 LLM 调用时传入
#
# 注意：
#   - 工具名重复注册时应抛出明确异常，避免静默覆盖

from .schema import ToolSchema


class FuncTuple:

    def __init__(self, func: callable, schema: ToolSchema):
        self._func = func
        self._schema = schema

    @property
    def func(self):
        return self._func

    @property
    def schema(self):
        return self._schema


class ToolRegistry:

    def __init__(self):
        self.registry = dict()

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
