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
from tools.schema import ToolSchema
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


def _openai_tools(tools: list[ToolSchema]):
    """
    用户提供给模型的工具列表，转换为 OpenAI function calling 所需的格式。
    将 ToolSchema 列表转换为 OpenAI function calling 所需的 dict 列表。
    """
    function_list = []
    for tool in tools:
        properties = {}
        for tool_name in tool.parameters:
            properties[tool_name] = {
                "type": tool.parameters[tool_name].parameter_type,
                "description": tool.parameters[tool_name].description,
            }

        function_list.append(
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                    },
                },
            }
        )
    return function_list
