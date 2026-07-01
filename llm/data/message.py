# 框架内部使用的消息/响应数据结构，与任何 provider SDK 无关。
#
# ToolCall 定义在 tools/schema.py（避免 tools ↔ llm 循环依赖），此处从那里 import。
#
# 定义以下数据类：
#
#   Message:
#     - role: Literal["system", "user", "assistant", "tool"]
#     - content: str | None
#     - tool_calls: list[ToolCall] | None   # role=assistant 时可能有值
#     - tool_call_id: str | None            # role=tool 时必须有值
#
#   LLMResponse:
#     - message: Message           # assistant 消息
#     - finish_reason: str         # "stop" | "tool_calls" | "length" | ...
#     - usage: dict | None         # token 用量统计（可选）

from pydantic.dataclasses import dataclass
from tools.schema import ToolCall  # noqa: F401 — re-exported for llm 包内使用


@dataclass
class Message:
    role: str
    content: str | list | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None


@dataclass
class LLMResponse:
    message: Message
    finish_reason: str
    usage: dict | None = None
