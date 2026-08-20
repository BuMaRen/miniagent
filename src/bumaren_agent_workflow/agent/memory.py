"""ConversationMemory —— Agent 的对话记忆。

管理一次 Agent 运行内部的消息历史。注意区分两种"记忆":
  - 这里的对话记忆:短期的、单个 Agent 运行内的 LLM 消息序列。
  - State Store(state/):跨 Stage、结构化的长期共享事实(如故事圣经)。
两者职责分开——用摘要保证连贯,用结构化状态保证事实一致。

压缩(总结旧消息以腾出上下文空间)的职责划分:
  - Memory 只提供"提示 + 改写入口"——是否该压缩(needs_compaction)、
    压缩哪些消息安全(compaction_candidates,负责保证不切断工具调用/结果配对),
    以及压缩结果如何回写(apply_compaction)。
  - 真正"怎么总结"(调 LLM 还是规则、摘要措辞)交给 Agent——因为只有 Agent
    同时持有 LLMClient,而且具体 Prompt 措辞属于场景层,不属于这一层。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from bumaren_agent_workflow.llm.message import Message

# 压缩后至少保留的最近消息条数,保证 Agent 仍能看到近期上下文。
_KEEP_RECENT = 4


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
        """追加一条消息。"""
        self.messages.append(message)

    def render(self) -> list[Message]:
        """渲染为发送给 LLM 的完整消息序列(system_prompt + messages)。"""
        rendered: list[Message] = []
        if self.system_prompt:
            rendered.append(Message(role="system", content=self.system_prompt))
        rendered.extend(self.messages)
        return rendered

    def needs_compaction(self) -> bool:
        """是否已达到需要压缩的软上限,供 Agent 决定何时触发总结。"""
        return self.max_tokens is not None and self._estimate_tokens() > self.max_tokens

    def compaction_candidates(self) -> list[Message]:
        """返回可安全总结的较早消息,供 Agent 拿去生成摘要。

        切分点保证:至少保留最近 _KEEP_RECENT 条不参与总结,且不会落在
        assistant 的工具调用与其对应 tool 结果消息之间。
        """
        return self.messages[: self._compaction_boundary()]

    def apply_compaction(self, summary: str) -> None:
        """用一条摘要消息替换 compaction_candidates() 对应的较早消息。

        由 Agent 在拿到摘要文本(通常来自一次 LLM 总结调用)后回写。

        注意:这里重新计算一次切分点,而不是复用 compaction_candidates() 当时
        算出的那个——因为 _compaction_boundary() 是纯函数,只要 self.messages
        在两次调用之间没被改动,重算结果必然一致,不需要额外传一个 split/句柄。
        但这也意味着"两次调用之间 self.messages 不可变"是一个隐式契约,此处
        不做校验;若中途有代码往 messages 里 append(如并发写入),重算出的
        split 就可能与 summary 实际总结的内容对不上,导致误删未被总结的新消息
        或切分错位。目前的调用方式(Agent._compact 内两次调用间只做一次同步
        的 LLM 摘要请求,不触碰 memory)保证了这个前提成立。
        """
        split = self._compaction_boundary()
        if split <= 0:
            return  # 没有可压缩的旧内容,忽略
        recent = self.messages[split:]
        self.messages = [Message(role="system", content=summary), *recent]

    def _compaction_boundary(self) -> int:
        """找压缩切分点:保留最近 _KEEP_RECENT 条,且不能切在 assistant 的
        工具调用与其对应 tool 结果消息之间。"""
        boundary = max(0, len(self.messages) - _KEEP_RECENT)
        while boundary > 0 and self.messages[boundary].role == "tool":
            boundary -= 1
        return boundary

    def _estimate_tokens(self) -> int:
        """估算当前记忆占用的 token 数(含 system_prompt)。"""
        total = _approx_tokens(self.system_prompt)
        total += sum(_approx_tokens(_message_text(m)) for m in self.messages)
        return total


def _approx_tokens(text: str | None) -> int:
    """粗略估算 token 数(约 4 字符 ≈ 1 token),不依赖具体 Provider 的分词器。"""
    return max(1, (len(text) + 3) // 4) if text else 0


def _message_text(message: Message) -> str:
    """取一条消息用于 token 估算的纯文本表示。"""
    parts = [message.content or ""]
    parts.extend(f"{tc.name}({tc.arguments})" for tc in message.tool_calls)
    return " ".join(p for p in parts if p)
