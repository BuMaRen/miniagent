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


from llm.base.client import LLMClient
from llm.data.message import Message


class ConversationContext:

    def __init__(self, client: LLMClient, system_prompt: str, threshold: int = 20):
        self._client = client
        self._threshold = threshold
        self._origin_system_prompt = system_prompt
        self._messages = list[Message]()
        self._messages.append(Message(role="system", content=system_prompt))

    def append(self, message: Message):
        self._messages.append(message)

    def messages(self) -> list[Message]:
        return self._messages

    def clear(self):
        self._messages.clear()

    def summarize_if_needed(self):
        msg_to_summarize = self._messages[1 : -self._threshold]
        if len(msg_to_summarize) > 0:
            # 调用 LLM 对历史对话做摘要压缩
            summary_prompt = (
                "Please briefly summarize the following conversation, retaining the key information:\n"
                + "\n".join([f"{msg.role}: {msg.content}" for msg in msg_to_summarize])
            )
            summary_resp = self._client.chat(
                messages=[Message(role="user", content=summary_prompt)]
            )
            summary_content = summary_resp.message.content
            # 将摘要以 system 消息形式保留，删除早期消息
            self._messages = [
                Message(role="system", content=self._origin_system_prompt),
                Message(role="system", content=f"Conversation summary: {summary_content}")
            ] + self._messages[-self._threshold :]
