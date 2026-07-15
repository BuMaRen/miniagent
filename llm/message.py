"""标准化消息与工具调用数据结构。

统一不同 Provider 的消息格式,Agent / Memory 只依赖这里的类型,不感知
具体厂商的字段差异。Provider 实现层负责在这些类型与厂商 API 之间转换。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["system", "user", "assistant", "tool"]


@dataclass
class ToolCall:
    """模型发起的一次工具调用请求。"""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class Message:
    """一条对话消息。

    Attributes:
        role:         system / user / assistant / tool。
        content:      文本内容(assistant 发起工具调用时可为空)。
        tool_calls:   assistant 消息携带的工具调用请求列表。
        tool_call_id: role == "tool" 时,对应的 ToolCall.id。
    """

    role: Role
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
