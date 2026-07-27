"""AnthropicClient —— Anthropic Messages API 实现。

与 OpenAI 的关键差异(转换时需注意):
  - system 是顶层参数,不放在 messages 列表里;需要从 list[Message] 中把
    role == "system" 的消息抽出来拼成一个字符串单独传。
  - Anthropic 没有 "tool" role:工具执行结果要装成一条 role="user" 消息,
    content 是一个 tool_result 内容块(tool_use_id 对应发起调用时的 id)。
  - assistant 的工具调用不是独立字段,而是 content 里的 tool_use 内容块;
    对应地,一条 assistant 消息可以同时含文本块和多个 tool_use 块。
  - 响应 message.content 是内容块列表,需要分别抽取 text 块(拼成
    Message.content)和 tool_use 块(转成 ToolCall)。
  - max_tokens 是必填参数,若调用方未传则给一个默认值兜底。
"""

from __future__ import annotations

from typing import Any

from anthropic import Anthropic

from llm.client import LLMClient, ChatResponse
from llm.message import Message, ToolCall
from tools.schema import ToolSchema

_DEFAULT_MAX_TOKENS = 4096


class AnthropicClient(LLMClient):
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str | None = None,
        **default_params: Any,
    ) -> None:
        self._model = model
        self._default_params = default_params
        self._client = Anthropic(api_key=api_key, base_url=base_url)

    def chat(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        response_schema: dict[str, Any] | None = None,
        **params: Any,
    ) -> ChatResponse:
        system = _extract_system(messages)

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": _to_anthropic_messages(messages),
            "max_tokens": _DEFAULT_MAX_TOKENS,
            **self._default_params,
            **params,
        }
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = [t.to_anthropic() for t in tools]
        if response_schema is not None:
            payload["output_config"] = _build_output_config(response_schema)

        response = self._client.messages.create(**payload)

        content_text: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in response.content:
            if block.type == "text":
                content_text.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(id=block.id, name=block.name, arguments=dict(block.input))
                )

        message = Message(
            role="assistant",
            content="\n".join(content_text) if content_text else None,
            tool_calls=tool_calls,
        )

        usage = response.usage.model_dump() if response.usage else {}

        return ChatResponse(message=message, tool_calls=tool_calls, usage=usage)


def _build_output_config(schema: dict[str, Any]) -> dict[str, Any]:
    """把 provider-neutral 的 JSON Schema 包成 Anthropic 的 output_config 结构。"""
    return {"format": {"type": "json_schema", "schema": schema}}


def _extract_system(messages: list[Message]) -> str | None:
    """把 system 消息拼成一个字符串,供顶层 system 参数使用。"""
    parts = [m.content for m in messages if m.role == "system" and m.content]
    return "\n\n".join(parts) if parts else None


def _to_anthropic_messages(messages: list[Message]) -> list[dict[str, Any]]:
    """把框架 Message 列表转成 Anthropic 的 messages 结构(system 已被剔除)。

    同一轮并行工具调用产生的多条 tool 消息,会合并进同一条 user 消息的多个
    tool_result 内容块——分开发送成多条 user 消息会让模型逐渐停止并行调用。
    """
    result: list[dict[str, Any]] = []
    in_tool_group = False
    for m in messages:
        # system 消息已被剔除,不再发送给模型
        if m.role == "system":
            continue
        # role="tool" 的消息是工具执行结果,要装成一条 role="user" 消息,content 是一个
        if m.role == "tool":
            block = {
                "type": "tool_result",
                "tool_use_id": m.tool_call_id,
                "content": m.content or "",
            }
            if in_tool_group:
                result[-1]["content"].append(block)
            else:
                result.append({"role": "user", "content": [block]})
                in_tool_group = True
            continue
        in_tool_group = False
        # role="assistant" 的消息可能同时含文本块和多个工具调用块,要把工具调用块转成 tool_use 内容块
        if m.tool_calls:
            content: list[dict[str, Any]] = []
            if m.content:
                content.append({"type": "text", "text": m.content})
            content.extend(
                {
                    "type": "tool_use",
                    "id": tc.id,
                    "name": tc.name,
                    "input": tc.arguments,
                }
                for tc in m.tool_calls
            )
            result.append({"role": m.role, "content": content})
            continue

        result.append({"role": m.role, "content": m.content or ""})

    return result
