"""ZhipuClient —— 智谱 AI(GLM 系列)官方 zai-sdk 实现。

zai-sdk 的 chat.completions 接口与 OpenAI 的线上格式基本一致(同一套
choices[0].message / delta.tool_calls 结构),因此消息转换逻辑与
llm/providers/openai.py 基本相同,仅有两点差异:
  - 客户端类是 zai.ZhipuAiClient;base_url 为 None 时,SDK 内部已默认指向
    官方地址 https://open.bigmodel.cn/api/paas/v4,无需在这里另行兜底。
  - GLM 的思考模式(thinking)会在响应/流式 delta 里多带一个
    reasoning_content 字段;框架的 Message/StreamEvent 目前不区分"思考"与
    "正文",这里不做透传,只取 content。
"""

from __future__ import annotations

import json
from typing import Any, Iterator

from zai import ZhipuAiClient

from llm.client import LLMClient, ChatResponse, StreamEvent
from llm.message import Message, ToolCall
from tools.schema import ToolSchema


class ZhipuClient(LLMClient):
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str | None = None,
        **default_params: Any,
    ) -> None:
        self._model = model
        self._default_params = default_params
        self._client = ZhipuAiClient(api_key=api_key, base_url=base_url)

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
            "messages": [_to_zhipu_message(m) for m in messages],
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
            "messages": [_to_zhipu_message(m) for m in messages],
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
        # 按 index 累积工具调用增量:与 OpenAI 一致,name/arguments 拆在多个
        # chunk 里下发,同一个 tool_call 的每个字段要按 index 对齐累加。
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
    """把 provider-neutral 的 JSON Schema 包成智谱(OpenAI 兼容)的 response_format 结构。"""
    return {
        "type": "json_schema",
        "json_schema": {"name": "output", "schema": schema, "strict": True},
    }


def _to_zhipu_message(message: Message) -> dict[str, Any]:
    """把框架的 Message 转成智谱(OpenAI 兼容)的 messages 结构。"""
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
