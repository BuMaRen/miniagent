"""ZhipuClient —— 智谱 AI(GLM 系列)官方 zai-sdk 实现。

zai-sdk 的 chat.completions 接口与 OpenAI 的线上格式基本一致(同一套
choices[0].message / delta.tool_calls 结构),因此消息转换逻辑与
llm/providers/openai.py 基本相同,但有两点需要单独适配:

  - 结构化输出:智谱的 response_format 只有 {"type": "json_object"}(保证是
    合法 JSON,不支持像 OpenAI/Anthropic 那样把 schema 直接内嵌进请求做强
    约束——参考官方示例"智谱结构化输出示例.PY":schema 是通过 prompt 告知
    模型、返回后再校验的)。这里对应地把 provider-neutral 的 response_schema
    转成一条追加的 system 消息(而不是塞进 response_format),实际的结构是否
    合规,由上层 engine.stage.Stage.output_schema.validate() 统一兜底校验,
    与其他 Provider 一致,这里不重复做 jsonschema 校验。

  - 思考模式(thinking):GLM 默认开着,不在这里强行关掉——小说这类创作场景
    恰恰需要它把情节/爽点先想清楚再落笔,关了思考等于放弃了模型的主要产出
    质量来源。调试时发现的真实问题不是"思考模式本身不能用",而是偶发(不是
    每次都发生,实测约几分之一概率)出现模型把整轮 completion_tokens 都花在
    思考上、最终 content 是空字符串——且不是被 max_tokens 截断(实测
    completion_tokens 远小于配置的 max_tokens),是模型自己在思考后没有再
    吐出正文就把这一轮结束了。这是模型侧偶发的"轮次作废",不是配置问题,
    重试同一份请求通常就能拿到正常回复。所以这里的修复是:非流式 chat()
    和流式 stream() 都在"content 与 tool_calls 双双为空"时原地重试
    _EMPTY_TURN_MAX_RETRIES 次,而不是关闭思考;stream() 的重试是安全的,
    因为只有当这一轮从头到尾都没有任何 delta.content 时才会触发重试,此时
    调用方还没收到过任何增量,重开一轮对调用方完全透明。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Iterator

from zai import ZhipuAiClient

from bumaren_agent_workflow.llm.client import LLMClient, ChatResponse, StreamEvent
from bumaren_agent_workflow.llm.message import Message, ToolCall
from bumaren_agent_workflow.tools.schema import ToolSchema

logger = logging.getLogger(__name__)

_EMPTY_TURN_MAX_RETRIES = 2  # 加上首次请求,最多尝试 3 次


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
            payload["messages"] = _append_schema_instruction(payload["messages"], response_schema)
            payload["response_format"] = _build_response_format()

        for attempt in range(_EMPTY_TURN_MAX_RETRIES + 1):
            completion = self._client.chat.completions.create(**payload)
            choice = completion.choices[0]
            message_data = choice.message

            tool_calls = [
                ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=json.loads(tc.function.arguments or "{}"),
                )
                for tc in (message_data.tool_calls or [])
            ]

            if message_data.content or tool_calls:
                message = Message(role="assistant", content=message_data.content, tool_calls=tool_calls)
                usage = completion.usage.model_dump() if completion.usage else {}
                return ChatResponse(
                    message=message, 
                    tool_calls=tool_calls, 
                    usage=usage,
                    stop_reason=choice.finish_reason,
                )

            logger.warning(
                "ZhipuClient.chat: 第 %d 次尝试 content 与 tool_calls 均为空(疑似思考模式"
                "未吐出正文,completion_tokens=%s),%s",
                attempt + 1,
                completion.usage.completion_tokens if completion.usage else "?",
                "重试" if attempt < _EMPTY_TURN_MAX_RETRIES else "已达最大重试次数,原样返回空结果",
            )

        usage = completion.usage.model_dump() if completion.usage else {}
        return ChatResponse(message=Message(role="assistant", content=None), usage=usage)

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
            payload["messages"] = _append_schema_instruction(payload["messages"], response_schema)
            payload["response_format"] = _build_response_format()

        for attempt in range(_EMPTY_TURN_MAX_RETRIES + 1):
            content_parts: list[str] = []
            # 按 index 累积工具调用增量:与 OpenAI 一致,name/arguments 拆在多个
            # chunk 里下发,同一个 tool_call 的每个字段要按 index 对齐累加。
            tool_call_chunks: dict[int, dict[str, Any]] = {}
            usage: dict[str, Any] = {}
            stop_reason: str | None = None

            for chunk in self._client.chat.completions.create(**payload):
                if chunk.usage:
                    usage = chunk.usage.model_dump()
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                if choice.finish_reason:
                    stop_reason = choice.finish_reason
                delta = choice.delta

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

            if content_parts or tool_calls:
                message = Message(
                    role="assistant",
                    content="".join(content_parts) or None,
                    tool_calls=tool_calls,
                )
                yield StreamEvent(
                    done=True,
                    response=ChatResponse(
                        message=message, 
                        tool_calls=tool_calls, 
                        usage=usage,
                        stop_reason=stop_reason,
                    ),
                )
                return

            # 这一轮从未产出过 delta.content,也没有 tool_calls——调用方还没收到
            # 任何增量,原地重开一轮对调用方是透明的(不会出现"补发"或"撤回"）。
            logger.warning(
                "ZhipuClient.stream: 第 %d 次尝试全程没有 content 或 tool_calls(疑似思考模式"
                "未吐出正文),%s",
                attempt + 1,
                "重试" if attempt < _EMPTY_TURN_MAX_RETRIES else "已达最大重试次数,原样返回空结果",
            )

        yield StreamEvent(
            done=True,
            response=ChatResponse(message=Message(role="assistant", content=None), usage=usage),
        )


_SCHEMA_INSTRUCTION_TEMPLATE = (
    "请仅输出一个符合以下 JSON Schema 的 JSON 对象,不要包含其他任何文字说明或 "
    "markdown 代码块:\n{schema}"
)


def _build_response_format() -> dict[str, Any]:
    """智谱的结构化输出只支持 json_object(保证语法合法),不支持像 OpenAI/
    Anthropic 那样在 response_format 里内嵌 schema 做强约束,schema 改由
    _append_schema_instruction 通过一条 system 消息告知模型。"""
    return {"type": "json_object"}


def _append_schema_instruction(
    zhipu_messages: list[dict[str, Any]], schema: dict[str, Any]
) -> list[dict[str, Any]]:
    """把 provider-neutral 的 JSON Schema 追加成一条 system 消息,而不是塞进
    response_format——放在消息序列末尾而非最前面,是为了在多轮 agentic loop
    里保持对最新一次要求的强提醒(近因效应),不被更早的 system 消息稀释。"""
    instruction = _SCHEMA_INSTRUCTION_TEMPLATE.format(
        schema=json.dumps(schema, ensure_ascii=False)
    )
    return [*zhipu_messages, {"role": "system", "content": instruction}]


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
