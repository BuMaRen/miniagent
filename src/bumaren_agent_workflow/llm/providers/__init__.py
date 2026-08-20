"""具体 LLM Provider 实现。

每个 Provider 实现 llm.client.LLMClient 接口,负责在框架标准类型
(Message / ToolCall / ChatResponse)与厂商 API 之间做转换。

    OpenAIClient    —— OpenAI 兼容接口(也可对接 Ollama / vLLM 等兼容端点)
    AnthropicClient —— Anthropic Messages API
    ZhipuClient     —— 智谱 AI(GLM 系列)官方 zai-sdk,线上格式与 OpenAI 兼容

新增 Provider 时,照此新建一个模块实现同一接口即可。
"""

from bumaren_agent_workflow.llm.providers.openai import OpenAIClient
from bumaren_agent_workflow.llm.providers.anthropic import AnthropicClient
from bumaren_agent_workflow.llm.providers.zhipu import ZhipuClient

__all__ = ["OpenAIClient", "AnthropicClient", "ZhipuClient"]
