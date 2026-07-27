"""字数与结构校验工具集 —— 供章节审校 (3.8) 与最终校验 (3.10) 使用。

中文字数统计不能简单 len(text.split()),需要按字符数计;这里提供的是
Critic/QA 类 Stage 用来"量化判断"的小工具,判断本身(是否合格)仍由
Agent 结合 Critic 标准决定,工具只负责给出可靠的数字。
"""

from __future__ import annotations

from agent.toolset import ToolSet


def count_chinese_characters(text: str) -> int:
    """统计一段文本中的中文字数(不含标点与空白)。

    Args:
        text: 待统计的正文文本。
    """
    return sum(1 for ch in text if "一" <= ch <= "鿿")


def check_word_count_range(word_count: int, min_count: int, max_count: int) -> str:
    """检查字数是否落在目标区间内,返回人类可读的判断结果。

    Args:
        word_count: 实际字数。
        min_count: 目标区间下限。
        max_count: 目标区间上限。
    """
    if word_count < min_count:
        return f"偏短: {word_count} 字,低于下限 {min_count} 字"
    if word_count > max_count:
        return f"偏长: {word_count} 字,超过上限 {max_count} 字"
    return f"达标: {word_count} 字,落在 [{min_count}, {max_count}] 区间内"


QA_TOOLSET = ToolSet.from_funcs(
    "qa_toolset", [count_chinese_characters, check_word_count_range]
)
