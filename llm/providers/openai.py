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
from typing import Any
from openai import OpenAI

from llm.client import LLMClient, ChatResponse
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
        **params: Any,
    ) -> ChatResponse:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [_to_openai_message(m) for m in messages],
            **self._default_params,
            **params,
        }
        if tools:
            payload["tools"] = [t.to_openai() for t in tools]

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