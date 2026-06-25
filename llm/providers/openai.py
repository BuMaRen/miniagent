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
