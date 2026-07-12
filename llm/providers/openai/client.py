# OpenAIClient：LLMClient 的 OpenAI/Ollama 实现。
#
# 依赖：openai SDK（pip install openai）
#
# 构造参数：
#   - api_key: str
#   - base_url: str | None   # 传入时切换为 Ollama 等兼容接口
#
# 实现 _build_request：
#   - 将内部 Message 列表转为 openai SDK 所需的 dict 格式
#   - 将 ToolSchema 列表转为 openai function calling 格式
#
# 实现 _parse_response：
#   - 从 openai ChatCompletion 对象中提取 Message、finish_reason、usage
#   - 统一转换为框架内部的 LLMResponse

from llm.data.message import Message, LLMResponse
from llm.base.client import LLMClient
from tools.schema import ToolCall, ToolSchema
from openai import OpenAI

from .msgs import construct_messages, choice_to_message


class OpenAIClient(LLMClient):
    """OpenAIClient：LLMClient 的 OpenAI/Ollama 实现。
    """

    def __init__(self, api_key: str, base_url: str | None, model: str):
        """__init_ - 初始化 OpenAIClient

        Args:
            api_key (str): OpenAI API key
            base_url (str | None): Base URL for the API (optional, used for Ollama or other compatible interfaces)
            model (str): Model name to use for the requests
        """
        super().__init__()
        self._client = OpenAI(base_url=base_url, api_key=api_key)
        self.model = model

    def _send_request(self, request):
        """
        发送请求到 OpenAI（只负责发送这个动作），并返回原始响应。
        """
        request["model"] = self.model
        debug_resp = self._client.chat.completions.create(**request)
        # print(f"[DEBUG] OpenAI raw response: {debug_resp.model_dump()}")
        return debug_resp

    def _build_request(self, messages: list[Message], tools: list[ToolSchema] | None):
        """
        将内部 Message 列表和 ToolSchema 列表转换为 OpenAI SDK 所需的请求格式。
        """
        request = {}
        if tools:
            # 将 ToolSchema 列表转换为 OpenAI function calling 所需的 dict 列表
            request["tools"] = _openai_tools(tools)
            request["tool_choice"] = "auto"

        # 将内部 Message 列表转为 openai SDK 所需的 dict 格式
        msgs = [construct_messages(msg) for msg in messages]
        request["messages"] = msgs
        return request

    def _parse_response(self, raw_response) -> LLMResponse:
        mp = raw_response.model_dump()
        choice = mp["choices"][0]
        return LLMResponse(
            message=choice_to_message(choice),
            finish_reason=choice.get("finish_reason") or "",
            usage=mp.get("usage", dict()),
        )

    def stream_chat(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None,
        on_delta=None,
        on_reasoning_delta=None,
        max_tokens: int | None = None,
        extra_body: dict | None = None,
    ) -> LLMResponse:
        """
        以流式（SSE）方式发起请求，边到达边通过 on_delta(text_chunk) 回调吐出文本增量。

        新增方法，不改动 chat()/_send_request() 的既有行为，仅供需要观察生成进度、
        或需要规避非流式模式下"生成完才返回一个字节"导致的长时间静默（进而可能触发
        idle read timeout）的调用方使用。

        思考模式开启时，模型的推理过程通过 delta.reasoning_content 单独下发，不会出现在
        delta.content 里；如果只监听 on_delta，思考阶段会完全没有任何回调触发，看起来像
        "卡住没输出"。需要观察思考过程时请传 on_reasoning_delta。

        Args:
            messages: 对话消息列表
            tools: 可用工具列表
            on_delta: 每收到一段正文增量时调用一次，参数为该增量字符串
            on_reasoning_delta: 每收到一段思考过程增量时调用一次（仅思考模式开启时有值）
            max_tokens: 单次生成的最大 token 数上限，兜底防止异常情况下无限生成
            extra_body: 透传给 SDK 的额外请求字段（如 Qwen 的 {"enable_thinking": False}）

        Returns:
            LLMResponse: 与 chat() 相同的标准化响应
        """
        request = self._build_request(messages, tools)
        request["model"] = self.model
        request["stream"] = True
        request["stream_options"] = {"include_usage": True}
        if max_tokens is not None:
            request["max_tokens"] = max_tokens
        if extra_body is not None:
            request["extra_body"] = extra_body
        stream = self._client.chat.completions.create(**request)

        content_parts = []
        tool_calls_by_index: dict[int, dict] = {}
        finish_reason = ""
        usage = {}

        for chunk in stream:
            if chunk.usage:
                usage = chunk.usage.model_dump()
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            delta = choice.delta
            if delta.content:
                content_parts.append(delta.content)
                if on_delta:
                    on_delta(delta.content)
            reasoning_piece = getattr(delta, "reasoning_content", None)
            if reasoning_piece and on_reasoning_delta:
                on_reasoning_delta(reasoning_piece)
            for tc in delta.tool_calls or []:
                entry = tool_calls_by_index.setdefault(
                    tc.index, {"id": "", "name": "", "arguments": ""}
                )
                if tc.id:
                    entry["id"] = tc.id
                if tc.function:
                    if tc.function.name:
                        entry["name"] = tc.function.name
                    if tc.function.arguments:
                        entry["arguments"] += tc.function.arguments
            if choice.finish_reason:
                finish_reason = choice.finish_reason

        return LLMResponse(
            message=Message(
                role="assistant",
                content="".join(content_parts) or None,
                tool_calls=[
                    ToolCall(id=v["id"], name=v["name"], arguments=v["arguments"])
                    for v in tool_calls_by_index.values()
                ],
            ),
            finish_reason=finish_reason,
            usage=usage,
        )


def _openai_tools(tools: list[ToolSchema]):
    """
    用户提供给模型的工具列表，转换为 OpenAI function calling 所需的格式。
    将 ToolSchema 列表转换为 OpenAI function calling 所需的 dict 列表。
    """
    function_list = []
    for tool in tools:
        properties = {}
        required = []
        for tool_name in tool.parameters:
            properties[tool_name] = {
                "type": tool.parameters[tool_name].parameter_type,
                "description": tool.parameters[tool_name].description,
            }
            if tool.parameters[tool_name].required:
                required.append(tool_name)

        function_list.append(
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                    },
                },
            }
        )
    return function_list
