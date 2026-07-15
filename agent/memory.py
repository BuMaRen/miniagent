"""ConversationMemory —— Agent 的对话记忆。

管理一次 Agent 运行内部的消息历史,并在接近上下文窗口上限时做压缩/总结。
注意区分两种"记忆":
  - 这里的对话记忆:短期的、单个 Agent 运行内的 LLM 消息序列。
  - State Store(state/):跨 Stage、结构化的长期共享事实(如故事圣经)。
两者职责分开——用摘要保证连贯,用结构化状态保证事实一致。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from llm.message import Message


@dataclass
class ConversationMemory:
    """单个 Agent 运行内的消息历史。

    Attributes:
        system_prompt: 系统提示,常驻消息序列首位。
        messages:      对话消息列表(user/assistant/tool)。
        max_tokens:    触发压缩的软上限(可选)。
    """

    system_prompt: str = ""
    messages: list[Message] = field(default_factory=list)
    max_tokens: int | None = None

    def append(self, message: Message) -> None:
        """追加一条消息,必要时触发压缩。"""
        # TODO: self.messages.append(message); 若超过 max_tokens 调用 self.compress()。
        raise NotImplementedError

    def render(self) -> list[Message]:
        """渲染为发送给 LLM 的完整消息序列(system_prompt + messages)。"""
        raise NotImplementedError

    def compress(self) -> None:
        """在接近上下文上限时,把较早的消息总结为一条摘要以腾出空间。"""
        # TODO: 用 LLM 或规则把旧消息压缩成摘要消息,替换原始条目。
        raise NotImplementedError
