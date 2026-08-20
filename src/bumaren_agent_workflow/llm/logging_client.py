"""LoggingLLMClient —— 记录每次 chat() 的完整往返到磁盘。

包一层 LLMClient,不改变对外行为,只在每次 chat()/stream() 完成后把请求
(messages/tools/params)与返回(response)序列化写入 log_dir,一次调用一个
JSON 文件,便于运行结束后审计 Prompt 与模型回复。是否记录、记到哪里由调用方
决定是否构造本类包一层(见 scenarios/example/run.py 的 --log-chats)。
"""

from __future__ import annotations

import json
import threading
from itertools import count
from pathlib import Path
from typing import Any, Iterator

from bumaren_agent_workflow.llm.client import ChatResponse, LLMClient, StreamEvent
from bumaren_agent_workflow.llm.message import Message, ToolCall
from bumaren_agent_workflow.tools.schema import ToolSchema


class LoggingLLMClient(LLMClient):
    """把每次 chat() 的请求/响应落盘到 log_dir,一次调用一个文件。"""

    def __init__(self, inner: LLMClient, log_dir: Path) -> None:
        self._inner = inner
        self._log_dir = log_dir
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._counter = count(1)
        self._lock = threading.Lock()

    def chat(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        response_schema: dict[str, Any] | None = None,
        **params: Any,
    ) -> ChatResponse:
        response = self._inner.chat(messages, tools=tools, response_schema=response_schema, **params)
        self._write(messages, tools, params, response)
        return response

    def stream(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        response_schema: dict[str, Any] | None = None,
        **params: Any,
    ) -> Iterator[StreamEvent]:
        for event in self._inner.stream(messages, tools=tools, response_schema=response_schema, **params):
            if event.done and event.response is not None:
                self._write(messages, tools, params, event.response)
            yield event

    def _write(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None,
        params: dict[str, Any],
        response: ChatResponse,
    ) -> None:
        with self._lock:
            index = next(self._counter)
        payload = {
            "request": {
                "messages": [_message_to_dict(m) for m in messages],
                "tools": [t.name for t in tools] if tools else [],
                "params": params,
            },
            "response": {
                "message": _message_to_dict(response.message),
                "usage": response.usage,
                # stop_reason 是排查"内容被截断"的关键信号(Anthropic 为
                # "max_tokens",OpenAI 兼容协议为 finish_reason="length"):
                # 不落这个字段的话,日志只能看到截断后的残缺文本,分不清是
                # 模型自己写短了还是被 max_tokens 硬切断的。
                "stop_reason": response.stop_reason,
            },
        }
        path = self._log_dir / f"chat_{index:04d}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _message_to_dict(message: Message) -> dict[str, Any]:
    return {
        "role": message.role,
        "content": message.content,
        "tool_calls": [_tool_call_to_dict(tc) for tc in message.tool_calls],
        "tool_call_id": message.tool_call_id,
    }


def _tool_call_to_dict(tool_call: ToolCall) -> dict[str, Any]:
    return {"id": tool_call.id, "name": tool_call.name, "arguments": tool_call.arguments}
