"""LLM 抽象层。

统一的 LLMClient 接口 + 标准化的消息/工具调用数据结构,使 Agent 与具体
Provider(OpenAI 兼容、Anthropic、Ollama 等)解耦。框架不绑定任何 Provider。

    LLMClient        —— 抽象接口(chat / 可选 stream)
    Message, ToolCall —— 标准化数据结构
    providers/        —— 具体 Provider 实现
"""

from bumaren_agent_workflow.llm.client import LLMClient
from bumaren_agent_workflow.llm.message import Message, ToolCall

__all__ = ["LLMClient", "Message", "ToolCall"]
