"""具体 LLM Provider 实现。

每个 Provider 实现 llm.client.LLMClient 接口,负责在框架标准类型
(Message / ToolCall / ChatResponse)与厂商 API 之间做转换。

    OpenAIClient    —— OpenAI 兼容接口(也可对接 Ollama / vLLM 等兼容端点)
    AnthropicClient —— Anthropic Messages API

新增 Provider 时,照此新建一个模块实现同一接口即可。
"""

from llm.providers.openai import OpenAIClient
from llm.providers.anthropic import AnthropicClient

__all__ = ["OpenAIClient", "AnthropicClient"]
