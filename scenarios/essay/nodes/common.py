"""跨节点复用:Agent 组装、字数统计、判定合并。

字数上下限是否达标是"能算的",不交给模型判断(development-guide.md §9)——
annotate_word_counts/merge_rejection 都是纯函数,由 review/drafting 节点的
executor 在拿到 Agent 产出后调用,与 AI 给出的剧情/爆点驳回理由合并成统一的
verdict。
"""

from __future__ import annotations

import re
from typing import Any

from agent import Agent, ConversationMemory, ToolSet
from llm.client import LLMClient
from tools.registry import ToolRegistry

_WHITESPACE_RE = re.compile(r"\s+")


def make_agent(
    client: LLMClient,
    system_prompt: str,
    toolsets: tuple[ToolSet, ...] = (),
    max_steps: int = 12,
    output_schema: Any | None = None,
) -> Agent:
    agent = Agent(
        client=client,
        memory=ConversationMemory(system_prompt=system_prompt),
        registry=ToolRegistry(),
        max_steps=max_steps,
        output_schema=output_schema,
    )
    for toolset in toolsets:
        agent.load_toolset(toolset)
    return agent


def count_chars(text: str) -> int:
    """中文字数统计:去除所有空白字符后的字符数。"""
    return len(_WHITESPACE_RE.sub("", text or ""))


def annotate_word_counts(chapters: list[dict]) -> int:
    """按 content 重新计算每章 word_count(原地覆盖模型给出的数值),返回全篇总字数。

    模型自己数的字数不可信(LLM 不擅长精确计数),这里用代码兜底覆盖,
    保证后续判定(字数上下限)依据的是真实值。
    """
    total = 0
    for chapter in chapters:
        word_count = count_chars(chapter.get("content", ""))
        chapter["word_count"] = word_count
        total += word_count
    return total


def merge_rejection(
    ai_rejected: bool,
    ai_feedback: str,
    min_words: int,
    max_words: int,
    total_words: int,
) -> tuple[bool, str]:
    """把字数上下限的确定性判定与 AI 给出的剧情/爆点判定合并成统一 verdict。

    字数判定优先在 feedback 里列出(更具体、更容易一次性修对),AI 的判定
    理由跟在后面。任一方触发 rejected 都算 rejected。
    """
    reasons: list[str] = []
    if total_words < min_words:
        reasons.append(f"全篇总字数 {total_words} 低于下限 {min_words},需要扩写")
    elif total_words > max_words:
        reasons.append(f"全篇总字数 {total_words} 超过上限 {max_words},需要精简")

    if ai_rejected and ai_feedback:
        reasons.append(ai_feedback)

    rejected = bool(reasons)
    feedback = "；".join(reasons)
    return rejected, feedback
