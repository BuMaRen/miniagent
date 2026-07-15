"""ToolRegistry —— 工具注册表。

统一保管"工具名 -> (函数, schema)"的映射,供 Agent 加载 Skill 时登记、
供 LLMClient.chat 取用 schema 列表、供 ToolExecutor 按名查函数执行。
"""

from __future__ import annotations

from typing import Any, Callable

from tools.schema import ToolSchema


class ToolRegistry:
    def __init__(self) -> None:
        self._funcs: dict[str, Callable[..., Any]] = {}
        self._schemas: dict[str, ToolSchema] = {}

    def register(self, name: str, func: Callable[..., Any], schema: ToolSchema) -> None:
        """登记一个工具;遇到重名应报错(避免 Skill 之间静默覆盖)。"""
        # TODO: 校验 name 未占用后写入 self._funcs / self._schemas。
        raise NotImplementedError

    def unregister(self, name: str) -> None:
        """移除一个工具(load_skill(mode="replace") 会用到)。"""
        raise NotImplementedError

    def get(self, name: str) -> Callable[..., Any]:
        """按名取回工具函数,缺失时给出清晰错误。"""
        raise NotImplementedError

    def schemas(self) -> list[dict[str, Any]]:
        """返回全部工具的 schema(OpenAI 结构),下发给 LLM。"""
        # TODO: [s.to_openai() for s in self._schemas.values()]
        raise NotImplementedError
