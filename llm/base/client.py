# LLMClient：与 LLM provider 交互的抽象基类（ABC）。
#
# 定义统一接口，隔离 provider SDK 细节：
#   - chat(messages: list[Message], tools: list[ToolSchema] | None) -> LLMResponse
#       发送对话请求，返回标准化响应（不暴露 provider 原始对象）
#
# 子类须实现：
#   - _build_request(messages, tools)  将内部 Message 格式转换为 provider 所需格式
#   - _parse_response(raw)             将 provider 原始响应解析为 LLMResponse
#
# 通用能力在基类实现：
#   - 重试逻辑（指数退避）
#   - 超时控制（从 AgentConfig 读取）
#   - 请求/响应日志（DEBUG 级别）

from llm.base.message import LLMResponse, Message
from tools.schema import ToolSchema


class LLMClient:

    def chat(
        self, messages: list[Message], tools: list[ToolSchema] | None = None
    ) -> LLMResponse:
        """
        发送对话请求，返回标准化响应（不暴露 provider 原始对象）
        """
        # 构建 provider 请求
        request = self._build_request(messages, tools)

        # 发送请求并获取原始响应
        raw_response = self._send_request(request)

        # 解析原始响应为标准化 LLMResponse
        response = self._parse_response(raw_response)

        return response

    def _send_request(self, request):
        """
        发送请求到 LLM provider，并返回原始响应。
        子类可以重写此方法以实现自定义发送逻辑（如使用不同的 SDK）。
        """
        raise NotImplementedError

    def _build_request(self, messages: list[Message], tools: list[ToolSchema] | None):
        """
        将内部 Message 格式转换为 provider 所需格式。
        子类必须实现此方法。
        """
        raise NotImplementedError

    def _parse_response(self, raw_response):
        """
        将 provider 原始响应解析为标准化 LLMResponse。
        子类必须实现此方法。
        """
        raise NotImplementedError
