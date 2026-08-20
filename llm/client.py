"""LLMClient —— 大模型客户端抽象接口。

Agent 只依赖这个接口;新增一个 Provider 就是实现一遍它(见 llm/providers/)。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Iterator

from llm.message import Message, ToolCall
from tools.schema import ToolSchema

STREAM_MAX_TOKENS_THRESHOLD = 16384
"""请求的 max_tokens 超过该阈值时,chat() 自动改走 stream 请求:非流式请求在
大 max_tokens(长输出)场景下容易触发 HTTP 超时,调用方看到的仍是完整的
ChatResponse,无感知。"""


@dataclass
class ChatResponse:
    """一次 chat 调用的标准化返回。

    Attributes:
        message:     模型返回的 assistant 消息。
        tool_calls:  便捷字段,等价于 message.tool_calls;非空表示需要执行工具后再续。
        usage:       token 用量等元信息(可选,用于成本统计)。
        stop_reason: 本轮结束原因(如 "end_turn"/"tool_use"/"max_tokens" 等),各
                     Provider 取值不完全一致);用于判断输出是否被 max_tokens 截断。
    """

    message: Message
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    stop_reason: str | None = None


@dataclass
class StreamEvent:
    """stream() 产出的一个事件。

    Attributes:
        delta:    本次新增的文本片段;非文本事件(如结束事件)时为 None。
        done:     是否为流的最后一个事件。
        response: 仅当 done=True 时非空,内容与 chat() 的返回等价(完整
                  message / tool_calls / usage),供调用方复用工具调用续写逻辑。
    """

    delta: str | None = None
    done: bool = False
    response: ChatResponse | None = None


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
        response_schema: dict[str, Any] | None = None,
        **params: Any,
    ) -> Iterator[StreamEvent]:
        """流式返回(可选能力)。默认不支持,需要时由具体 Provider 覆写。

        实现约定:边生成边 yield StreamEvent(delta=...);生成结束后 yield 一个
        StreamEvent(done=True, response=...) 收尾,response 与 chat() 的返回等价。
        """
        raise NotImplementedError("this provider does not support streaming")

    def _should_stream(self, max_tokens: int | None) -> bool:
        """判断本次 chat() 是否应改走 stream 请求(见 STREAM_MAX_TOKENS_THRESHOLD)。

        Args:
            max_tokens: 本次请求实际生效的 max_tokens(已合并默认参数与调用方
                        传入的 params 之后的最终值);None 表示未设置该参数。
        """
        return max_tokens is not None and max_tokens >= STREAM_MAX_TOKENS_THRESHOLD

    def _chat_via_stream(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None,
        response_schema: dict[str, Any] | None,
        **params: Any,
    ) -> ChatResponse:
        """内部改走 stream() 拿完整 ChatResponse,供 chat() 在长输出场景下调用。

        只取收尾事件里的 response,过程中的文本增量丢弃不用——chat() 的调用方
        要的是完整结果,不是逐字输出。
        """
        for event in self.stream(
            messages, tools=tools, response_schema=response_schema, **params
        ):
            if event.done:
                if event.response is None:
                    raise RuntimeError("stream() 的收尾事件缺少 response")
                return event.response
        raise RuntimeError("stream() 结束但未产出收尾事件")
