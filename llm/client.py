"""LLMClient —— 大模型客户端抽象接口。

Agent 只依赖这个接口;新增一个 Provider 就是实现一遍它(见 llm/providers/)。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from llm.message import Message, ToolCall
from tools.schema import ToolSchema


@dataclass
class ChatResponse:
    """一次 chat 调用的标准化返回。

    Attributes:
        message:    模型返回的 assistant 消息。
        tool_calls: 便捷字段,等价于 message.tool_calls;非空表示需要执行工具后再续。
        usage:      token 用量等元信息(可选,用于成本统计)。
    """

    message: Message
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)


class LLMClient(ABC):
    """大模型客户端接口。"""

    @abstractmethod
    def chat(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        response_schema: dict[str, Any] | None = None,
        **params: Any,
    ) -> ChatResponse:
        """发起一次对话补全。

        Args:
            messages: 完整消息序列(由 ConversationMemory.render() 产出)。
            tools:    可用工具的 ToolSchema 列表(由 ToolRegistry.schemas() 产出,
                      provider-neutral),各 Provider 实现内部自行转换成对应格式
                      (如 OpenAI 走 schema.to_openai());None 表示本次不提供工具。
            response_schema: provider-neutral 的 JSON Schema(由
                      state.schema.StateSchema.to_json_schema() 产出),非 None 时
                      要求各 Provider 开启结构化输出模式,保证回复是符合该 schema
                      的 JSON;各 Provider 内部自行转换成对应的请求形状(如 OpenAI
                      的 response_format、Anthropic 的 output_config)。
            params:   温度、max_tokens 等 Provider 参数。
        """

    def stream(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        **params: Any,
    ):
        """流式返回(可选能力)。默认不支持,需要时由具体 Provider 覆写。"""
        raise NotImplementedError("this provider does not support streaming")
