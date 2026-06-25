# 框架内部使用的消息/响应数据结构，与任何 provider SDK 无关。
#
# 定义以下数据类（dataclass 或 TypedDict）：
#
#   Message:
#     - role: Literal["system", "user", "assistant", "tool"]
#     - content: str | None
#     - tool_calls: list[ToolCall] | None   # role=assistant 时可能有值
#     - tool_call_id: str | None            # role=tool 时必须有值
#
#   ToolCall:
#     - id: str
#     - name: str
#     - arguments: str   # JSON 字符串
#
#   LLMResponse:
#     - message: Message           # assistant 消息
#     - finish_reason: str         # "stop" | "tool_calls" | "length" | ...
#     - usage: dict | None         # token 用量统计（可选）

from pydantic.dataclasses import dataclass


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str  # JSON 字符串


@dataclass
class Message:
    role: str
    content: str | None = None
    tool_calls: list["ToolCall"] | None = None
    tool_call_id: str | None = None


@dataclass
class LLMResponse:
    message: Message
    finish_reason: str
    usage: dict | None = None
