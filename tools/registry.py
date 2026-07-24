"""ToolRegistry —— 工具注册表。

统一保管"工具名 -> (函数, schema)"的映射,供 Agent 加载 ToolSet 时登记、
供 LLMClient.chat 取用 schema 列表、供 ToolExecutor 按名查函数执行。
"""

from __future__ import annotations

from typing import Any, Callable

from tools.schema import ToolSchema, schema_from_func


class ToolRegistry:
    def __init__(self) -> None:
        self._funcs: dict[str, Callable[..., Any]] = {}
        self._schemas: dict[str, ToolSchema] = {}

    def register(self, name: str, func: Callable[..., Any], schema: ToolSchema) -> bool:
        """登记一个工具; 遇到重名返回 False,否则返回 True。

        与 unregister(name) / get(name) 保持同样的 name 优先签名。name 须与
        schema.name 一致(否则 registry 的 key 和下发给 LLM 的 schema.name 会
        对不上),不一致时报错。
        """
        if name != schema.name:
            raise ValueError(f"name({name!r}) 与 schema.name({schema.name!r}) 不一致")
        if name in self._funcs:
            return False
        self._funcs[name] = func
        self._schemas[name] = schema
        return True

    def unregister(self, name: str) -> None:
        """移除一个工具(load_toolset(mode="replace") 会用到)。"""
        self._funcs.pop(name, None)
        self._schemas.pop(name, None)

    def get(self, name: str) -> Callable[..., Any]:
        """按名取回工具函数,缺失时给出清晰错误。"""
        try:
            return self._funcs[name]
        except KeyError:
            raise KeyError(f"工具 '{name}' 未注册") from None

    def schemas(self) -> list[ToolSchema]:
        """返回全部工具的 ToolSchema(provider-neutral),由 LLMClient 按需转换。"""
        return list(self._schemas.values())


# 全局默认注册表,供 Agent / LLMClient / ToolExecutor 共享
default_registry = ToolRegistry()


def tool(func):
    """装饰器:把一个函数注册为工具,并自动生成 schema。

    用法:
        @tool
        def my_tool(x: int, y: str = "default") -> str:
            \"\"\"这是一个示例工具。

            Args:
                x: 一个整数参数。
                y: 一个字符串参数,有默认值。
            \"\"\"
            return f"x={x}, y={y}"

    这会把 my_tool 注册到默认注册表(default_registry),并生成对应的 ToolSchema。
    """
    default_registry.register(func.__name__, func, schema_from_func(func))
    return func
