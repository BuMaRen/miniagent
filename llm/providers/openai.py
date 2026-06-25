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

from tkinter import Message

import openai

from llm.base.client import LLMClient
from tools.schema import ToolSchema


class OpenAIClient(LLMClient):

    def __init__(self, api_key: str, base_url: str | None = None):
        self.api_key = api_key
        self.base_url = base_url
        openai.api_key = api_key
        if base_url:
            openai.api_base = base_url
    
    def _build_request(self, messages: list[Message], tools: list[ToolSchema] | None):
        pass
    
    def _parse_response(self, raw_response):
        pass