"""大纲结构体检 —— 用确定性规则挡掉"根本不可能写成 8000-10000 字"的大纲。

和 style.py 是同一个思路:能算的就别让模型判断。总字数是否落在目标区间、
小节编号是否连续、爽点的铺垫小节是否排在回收小节之前 —— 这些都是算术题,
交给 LLM Critic 只会得到"看起来没问题"。这里先算,算出的问题原样进 Critic 的
feedback,下一轮大纲照着改。

与 style.py 不同,本模块不导出 ToolSet:这些检查在 Stage 的 executor 里**无条件
执行**(见 stages.build_outline_critic_stage),而不是等模型想起来才调用。挂成
工具反而会让"该不该检查"变成模型的自由裁量。

本模块不含任何题材语义,只认大纲的形状。
"""

from __future__ import annotations

from typing import Any

# 单节字数的合理区间。低于下限说明大纲把一节切得太碎(读起来像流水账),高于
# 上限则说明一节塞了太多事,后面撰写时必然超纲或者草草收尾。
# 上限给到 2600 而不是掐着 2200:用户可以指定 section_count(如 4 节写 8000-10000
# 字,每节就得 2000-2500),卡得太死会让大纲反复因为算术不达标被打回,而返工
# 一轮大纲比多写 400 字贵得多。
MIN_SECTION_BUDGET = 700
MAX_SECTION_BUDGET = 2600

# 短篇的小节数下限/上限。少于下限撑不起"起承转合 + 至少一次翻转",多于上限
# 每节就短到只剩梗概。
MIN_SECTION_COUNT = 4
MAX_SECTION_COUNT = 10


def outline_problems(
    sections: list[dict[str, Any]],
    payoffs: list[dict[str, Any]],
    target_word_count: list[int],
) -> list[str]:
    """列出大纲里确定性可判的问题,每条都写成可执行的修改要求;没有则返回空表。

    Args:
        sections: 大纲小节列表(至少含 index / word_budget / beat_summary)。
        payoffs:  爽点设计列表(至少含 setup_section / payoff_section)。
        target_word_count: 目标总字数区间 [下限, 上限]。
    """
    problems: list[str] = []
    if not sections:
        return ["大纲没有产出任何小节,请重新生成。"]

    min_total, max_total = (list(target_word_count) + [0, 0])[:2]

    count = len(sections)
    if count < MIN_SECTION_COUNT:
        problems.append(f"小节数只有 {count} 节,少于 {MIN_SECTION_COUNT} 节,撑不起完整的起落,请拆得更细。")
    if count > MAX_SECTION_COUNT:
        problems.append(f"小节数有 {count} 节,多于 {MAX_SECTION_COUNT} 节,每节会短到只剩梗概,请合并。")

    indexes = [s.get("index") for s in sections]
    if indexes != list(range(1, count + 1)):
        problems.append(f"小节 index 必须是从 1 开始连续的整数,当前是 {indexes}。")

    budgets = [int(s.get("word_budget") or 0) for s in sections]
    total = sum(budgets)
    if max_total and not (min_total <= total <= max_total):
        problems.append(
            f"各节 word_budget 合计 {total} 字,不在目标区间 [{min_total}, {max_total}] 内,"
            "请调整每节的字数预算(可以增删小节),使合计落进区间。"
        )
    off_range = [
        f"第{s.get('index')}节 {b} 字"
        for s, b in zip(sections, budgets)
        if not (MIN_SECTION_BUDGET <= b <= MAX_SECTION_BUDGET)
    ]
    if off_range:
        problems.append(
            f"下列小节的 word_budget 不在单节合理区间 [{MIN_SECTION_BUDGET}, {MAX_SECTION_BUDGET}] 内:"
            + "、".join(off_range)
            + "。"
        )

    empty_beats = [str(s.get("index")) for s in sections if not (s.get("beat_summary") or "").strip()]
    if empty_beats:
        problems.append(f"第 {'、'.join(empty_beats)} 节的 beat_summary 为空,请补上该节要发生的事。")

    valid_indexes = set(range(1, count + 1))
    for payoff in payoffs or []:
        setup = payoff.get("setup_section")
        pay = payoff.get("payoff_section")
        label = payoff.get("description") or payoff.get("id") or "(未命名爽点)"
        if setup not in valid_indexes or pay not in valid_indexes:
            problems.append(
                f"爽点“{label}”的 setup_section={setup}/payoff_section={pay} 指向了不存在的小节,"
                f"合法范围是 1-{count}。"
            )
        elif setup > pay:
            problems.append(
                f"爽点“{label}”的铺垫小节({setup})排在回收小节({pay})之后,"
                "爽点必须先压后放,请调整。"
            )
    if not payoffs:
        problems.append("没有规划任何爽点(payoffs),请至少给出 2-4 个铺垫-回收成对的爽点。")
    return problems


def section_length_problem(word_count: int, word_budget: int, tolerance: float = 0.25) -> str | None:
    """检查一节正文的字数是否偏离预算太多;没问题返回 None。

    容差默认 ±25%:小说不是填空题,硬卡到个位数只会逼模型注水或砍情节;但偏离
    过半就会让总字数失控 —— 短篇的总量本来就是靠各节预算加起来兜住的。

    Args:
        word_count:  实际汉字数。
        word_budget: 该节的字数预算。
        tolerance:   允许的相对偏差。
    """
    if word_budget <= 0:
        return None
    low = int(word_budget * (1 - tolerance))
    high = int(word_budget * (1 + tolerance))
    if word_count < low:
        return f"本节 {word_count} 字,低于预算 {word_budget} 字的下限 {low} 字,请补足(展开描写与铺垫,不要注水)。"
    if word_count > high:
        return f"本节 {word_count} 字,高于预算 {word_budget} 字的上限 {high} 字,请压缩(删枝蔓,不要删爽点)。"
    return None
