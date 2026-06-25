# ConversationContext：短期记忆，维护当前对话的完整 messages 列表。
#
# 功能：
#   - append(message: Message)           追加一条消息
#   - messages() -> list[Message]        返回当前全部消息（供 LLMClient 使用）
#   - clear()                            清空对话（开始新任务时调用）
#   - summarize_if_needed(threshold: int)
#       当 messages 数量超过 threshold 时，调用 LLM 对历史对话做摘要压缩，
#       将摘要以 system 消息形式保留，删除早期消息，避免超出上下文窗口
#
# 注意：
#   - messages 列表是 agentic loop 的核心数据，所有组件都从这里读写消息
#   - 摘要压缩是可选功能，简单实现可先跳过
