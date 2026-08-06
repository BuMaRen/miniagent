"""OpenAIClient —— OpenAI 兼容接口实现。

实现指导:
  - 构造参数:api_key、base_url(便于对接 Ollama / vLLM 等兼容端点)、model、默认参数。
  - chat():
      1. 把 list[Message] 转成 OpenAI 的 messages 结构(注意 tool 消息需带 tool_call_id,
         assistant 的 tool_calls 需要还原成 OpenAI 的 tool_calls 字段)。
      2. 把 tools(list[ToolSchema])逐个调用 .to_openai() 转成 OpenAI 的 tool 定义,
         再调用 chat.completions.create(model, messages, tools=...)。
      3. 把响应解析回框架的 ChatResponse:抽取 assistant message、tool_calls、usage。
  - 注意点(来自既往调试经验):
      * 部分模型/端点返回的 tool_calls 可能为 None,需判空,不能直接迭代。
      * 工具参数是 JSON 字符串,需要 json.loads 成 dict 再放进 ToolCall.arguments。
      * 编码类工具调用对小模型不稳定,必要时在场景层选用更大参数模型。
"""

from __future__ import annotations

import json
from typing import Any, Iterator
from openai import OpenAI

from llm.client import LLMClient, ChatResponse, StreamEvent
from llm.message import Message, ToolCall
from tools.schema import ToolSchema


class OpenAIClient(LLMClient):
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str | None = None,
        **default_params: Any,
    ) -> None:
        self._model = model
        self._default_params = default_params
        self._client = OpenAI(api_key=api_key, base_url=base_url)

    def chat(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        response_schema: dict[str, Any] | None = None,
        **params: Any,
    ) -> ChatResponse:
        # max_tokens 较大(长输出)时非流式请求容易触发 HTTP 超时,改走 stream
        # 内部拿完整结果,调用方仍然只看到一个同步的 ChatResponse。
        max_tokens = params.get("max_tokens", self._default_params.get("max_tokens"))
        if self._should_stream(max_tokens):
            return self._chat_via_stream(messages, tools, response_schema, **params)

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [_to_openai_message(m) for m in messages],
            **self._default_params,
            **params,
        }
        if tools:
            payload["tools"] = [t.to_openai() for t in tools]
        if response_schema is not None:
            payload["response_format"] = _build_response_format(response_schema)

        completion = self._client.chat.completions.create(**payload)
        choice = completion.choices[0].message

        tool_calls = [
            ToolCall(
                id=tc.id,
                name=tc.function.name,
                arguments=json.loads(tc.function.arguments or "{}"),
            )
            for tc in (choice.tool_calls or [])
        ]

        message = Message(
            role="assistant",
            content=choice.content,
            tool_calls=tool_calls,
        )

        usage = completion.usage.model_dump() if completion.usage else {}

        return ChatResponse(message=message, tool_calls=tool_calls, usage=usage)

    def stream(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        response_schema: dict[str, Any] | None = None,
        **params: Any,
    ) -> Iterator[StreamEvent]:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [_to_openai_message(m) for m in messages],
            "stream": True,
            # 让最后一个 chunk 带上 usage,行为与非流式 completion.usage 对齐。
            "stream_options": {"include_usage": True},
            **self._default_params,
            **params,
        }
        if tools:
            payload["tools"] = [t.to_openai() for t in tools]
        if response_schema is not None:
            payload["response_format"] = _build_response_format(response_schema)

        content_parts: list[str] = []
        # 按 index 累积工具调用增量:OpenAI 把 name/arguments 拆在多个 chunk 里下发,
        # 同一个 tool_call 的每个字段要按 index 对齐累加,收完才能整体解析。
        tool_call_chunks: dict[int, dict[str, Any]] = {}
        usage: dict[str, Any] = {}

        for chunk in self._client.chat.completions.create(**payload):
            if chunk.usage:
                usage = chunk.usage.model_dump()
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta

            if delta.content:
                content_parts.append(delta.content)
                yield StreamEvent(delta=delta.content)

            for tc in delta.tool_calls or []:
                entry = tool_call_chunks.setdefault(
                    tc.index, {"id": None, "name": "", "arguments": ""}
                )
                if tc.id:
                    entry["id"] = tc.id
                if tc.function:
                    if tc.function.name:
                        entry["name"] += tc.function.name
                    if tc.function.arguments:
                        entry["arguments"] += tc.function.arguments

        tool_calls = [
            ToolCall(
                id=entry["id"],
                name=entry["name"],
                arguments=json.loads(entry["arguments"] or "{}"),
            )
            for entry in (tool_call_chunks[i] for i in sorted(tool_call_chunks))
        ]

        message = Message(
            role="assistant",
            content="".join(content_parts) or None,
            tool_calls=tool_calls,
        )

        yield StreamEvent(
            done=True,
            response=ChatResponse(message=message, tool_calls=tool_calls, usage=usage),
        )


def _build_response_format(schema: dict[str, Any]) -> dict[str, Any]:
    """把 provider-neutral 的 JSON Schema 包成 OpenAI 的 response_format 结构。"""
    return {
        "type": "json_schema",
        "json_schema": {"name": "output", "schema": schema, "strict": True},
    }


def _to_openai_message(message: Message) -> dict[str, Any]:
    """把框架的 Message 转成 OpenAI 的 messages 结构。"""
    if message.role == "tool":
        return {
            "role": "tool",
            "content": message.content or "",
            "tool_call_id": message.tool_call_id,
        }

    result: dict[str, Any] = {"role": message.role, "content": message.content}

    if message.tool_calls:
        result["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.name,
                    "arguments": json.dumps(tc.arguments),
                },
            }
            for tc in message.tool_calls
        ]
    return result