# AnthropicClient：LLMClient 的 Anthropic Claude 实现。
#
# 依赖：anthropic SDK（pip install anthropic）
#
# 注意 Anthropic API 与 OpenAI 的主要差异：
#   - system 消息不放在 messages 列表里，而是单独的 system 参数
#   - 工具定义格式（input_schema vs parameters）不同
#   - tool result 的 role 是 "user"，内容为 content block 列表
#   - finish_reason 字段名为 stop_reason
#
# 实现 _build_request：
#   - 将 system 消息从 messages 中抽离，单独传给 system 参数
#   - 转换工具 Schema 格式
#
# 实现 _parse_response：
#   - 从 anthropic Message 对象中提取 content blocks
#   - 将 tool_use block 映射为内部 ToolCall 列表
