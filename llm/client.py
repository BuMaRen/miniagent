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
