"""文风体检 —— 把"AI 痕迹"从主观感受变成几个可计量的比率。

用户对这个场景的硬要求里,"不能有过明显的 AI 痕迹"是最难交给 LLM 自己把关的
一条:让 Critic 凭感觉判断,同一段文字这轮说通过、下轮说不通过,循环就退化成
掷骰子。好在被点名的三个毛病恰好都有形状:

  - 频繁的短句            -> 短句(不足 short_sentence_chars 字)占全部句子的比例
  - 很多单短句组成的段落  -> 只有一句话的段落占全部段落的比例
  - 描写非常零散          -> 长句(不少于 long_sentence_chars 字,通常是把环境/
                             动作/心理编织在一起的复合句)占比过低

于是这里先算数字,再把数字连同越界项一起交给 Critic:**数字负责兜底**(见
stages.py 里"体检不过一律判否"的强制判定),**Critic 负责数字覆盖不到的部分**
(错别字、语病、逻辑、人物)。两者都不越界。

阈值不是普适真理,是针对"中文短篇网文"这一体裁调出来的经验值;它们集中在
DEFAULT_THRESHOLDS 一处,场景方要收紧或放宽只改这一个对象。

本模块不含任何题材语义,只认中文文本的形状。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from agent.toolset import ToolSet

# 句末标点(含后置的引号/括号):中文小说里 "……" "!" "?" 与右引号常常连用,
# 切句时要把它们一并归到上一句,否则每段对白都会被切出一个空壳句。
_SENTENCE_END_RE = re.compile(r'(?<=[。!?！？…])(?=[^」』”"’)）\]】]|$)')

# 一句话里真正"算字数"的只有汉字:标点与空白不参与,免得靠堆标点把短句撑成长句。
_CJK_RE = re.compile(r"[一-鿿]")

# 常见的"AI 腔"套话。注意这里做的是**密度**检查而不是禁用词表:"仿佛""似乎"
# 本身都是正常的汉语词,问题出在整篇反复用同一批词组制造情绪。所以命中一次
# 不算问题,单位篇幅命中太多次才算(见 max_cliche_per_1000)。
_CLICHES: tuple[str, ...] = (
    "仿佛", "彷佛", "不禁", "似乎", "竟然", "缓缓开口", "淡淡地说", "淡淡道",
    "嘴角勾起", "嘴角微微", "一抹弧度", "瞳孔一缩", "瞳孔猛地", "眼神深处",
    "空气仿佛凝固", "空气凝固", "死一般的寂静", "鸦雀无声", "浑身一震",
    "心中一凛", "心头一紧", "不由自主地", "不为人知", "命运的齿轮",
    "在这一刻", "在那一瞬间", "整个世界", "无人知晓", "如同",
    "令人窒息", "不容置疑", "难以言喻", "毫无疑问",
)


@dataclass(frozen=True)
class StyleThresholds:
    """判定"是否有明显 AI 痕迹"的阈值。

    Attributes:
        short_sentence_chars: 少于多少汉字算"短句"。
        long_sentence_chars:  不少于多少汉字算"长句"(承载环境/心理的复合句)。
        max_short_sentence_ratio: 短句占比上限。网文本来就比纯文学短促,所以
            给到 0.45 而不是更严;真正的问题是通篇只有短句。
        max_single_sentence_paragraph_ratio: 单句成段的段落占比上限。留 0.30 是
            因为对白与关键的"顿"点本就该独立成段,禁绝反而不像小说。
        min_long_sentence_ratio: 长句占比下限。低于它说明描写被拆成了一地碎句。
        max_cliche_per_1000: 每千字套话命中次数上限。
        min_chars_for_check: 少于这么多字就不做比率判定 —— 样本太小时比率没有
            统计意义(两句话里有一句短句就是 50%),硬判只会制造无意义的返工。
    """

    short_sentence_chars: int = 12
    long_sentence_chars: int = 25
    max_short_sentence_ratio: float = 0.45
    max_single_sentence_paragraph_ratio: float = 0.30
    min_long_sentence_ratio: float = 0.15
    max_cliche_per_1000: float = 3.0
    min_chars_for_check: int = 300


DEFAULT_THRESHOLDS = StyleThresholds()


def count_chinese_characters(text: str) -> int:
    """统计一段文本里的汉字数(不含标点与空白),即中文语境下的"字数"。

    Args:
        text: 待统计的正文文本。
    """
    return len(_CJK_RE.findall(text))


def split_paragraphs(text: str) -> list[str]:
    """按空行/换行切出段落,丢掉空段。"""
    return [p.strip() for p in re.split(r"\n+", text or "") if p.strip()]


def split_sentences(text: str) -> list[str]:
    """按句末标点切出句子,丢掉空句。"""
    return [s.strip() for s in _SENTENCE_END_RE.split(text or "") if s.strip()]


def style_metrics(text: str) -> dict[str, Any]:
    """给一段正文做文风体检,返回句长/段落/套话的量化指标。

    指标含义:char_count 汉字数;paragraph_count 段落数;sentence_count 句子数;
    avg_sentence_chars 平均句长;short_sentence_ratio 短句占比(越高越像 AI 分镜
    脚本);long_sentence_ratio 长句占比(越低说明描写越零散);
    single_sentence_paragraph_ratio 单句成段的段落占比;cliche_per_1000 每千字
    套话密度;top_cliches 命中最多的几个套话及次数。

    Args:
        text: 待体检的正文文本。
    """
    paragraphs = split_paragraphs(text)
    sentences = split_sentences(text)
    char_count = count_chinese_characters(text)

    lengths = [count_chinese_characters(s) for s in sentences]
    sentence_count = len(sentences)
    short = sum(1 for n in lengths if n < DEFAULT_THRESHOLDS.short_sentence_chars)
    long_ = sum(1 for n in lengths if n >= DEFAULT_THRESHOLDS.long_sentence_chars)
    single = sum(1 for p in paragraphs if len(split_sentences(p)) <= 1)

    hits = {c: text.count(c) for c in _CLICHES}
    hits = {c: n for c, n in hits.items() if n}
    total_hits = sum(hits.values())

    def ratio(part: int, whole: int) -> float:
        return round(part / whole, 3) if whole else 0.0

    return {
        "char_count": char_count,
        "paragraph_count": len(paragraphs),
        "sentence_count": sentence_count,
        "avg_sentence_chars": round(sum(lengths) / sentence_count, 1) if sentence_count else 0.0,
        "short_sentence_ratio": ratio(short, sentence_count),
        "long_sentence_ratio": ratio(long_, sentence_count),
        "single_sentence_paragraph_ratio": ratio(single, len(paragraphs)),
        "cliche_per_1000": round(total_hits * 1000 / char_count, 2) if char_count else 0.0,
        "top_cliches": sorted(hits.items(), key=lambda kv: -kv[1])[:5],
    }


def style_violations(text: str) -> list[str]:
    """列出这段正文越过阈值的 AI 痕迹,每条都带上实测值与目标值;没有则返回空表。

    返回的每一条都写成"可执行的修改要求"而不是"评语",因为它会被原样塞进
    Critic 的 feedback,再由下一轮的撰写/精修节点照着改。

    Args:
        text: 待体检的正文文本。
    """
    m = style_metrics(text)
    t = DEFAULT_THRESHOLDS
    problems: list[str] = []

    # 样本太小时比率没有统计意义,只查套话密度。
    if m["char_count"] >= t.min_chars_for_check:
        if m["short_sentence_ratio"] > t.max_short_sentence_ratio:
            problems.append(
                f"短句过多:不足 {t.short_sentence_chars} 字的句子占 "
                f"{m['short_sentence_ratio']:.0%},超过上限 {t.max_short_sentence_ratio:.0%}。"
                "请把连续的主谓宾短句合并成有主次关系的复合句,只在真正需要停顿处保留短句。"
            )
        if m["single_sentence_paragraph_ratio"] > t.max_single_sentence_paragraph_ratio:
            problems.append(
                f"单句成段过多:只有一句话的段落占 {m['single_sentence_paragraph_ratio']:.0%},"
                f"超过上限 {t.max_single_sentence_paragraph_ratio:.0%}。"
                "请把相邻的单句段落并成 3-6 句的完整段落,只保留少数用于强调的独立成段。"
            )
        if m["long_sentence_ratio"] < t.min_long_sentence_ratio:
            problems.append(
                f"描写零散:不少于 {t.long_sentence_chars} 字的长句只占 "
                f"{m['long_sentence_ratio']:.0%},低于下限 {t.min_long_sentence_ratio:.0%}。"
                "请把环境、动作、心理编织进同一句里展开,不要把每个细节都拆成单独一句。"
            )
    if m["cliche_per_1000"] > t.max_cliche_per_1000:
        top = "、".join(f"{word}×{n}" for word, n in m["top_cliches"])
        problems.append(
            f"套话密度过高:每千字命中 {m['cliche_per_1000']} 次(上限 "
            f"{t.max_cliche_per_1000}),集中在:{top}。请换成具体的动作或细节描写,能删则删。"
        )
    return problems


def check_length(word_count: int, min_count: int, max_count: int) -> str:
    """检查字数是否落在目标区间内,返回人类可读的判断结果。

    Args:
        word_count: 实际字数(汉字数)。
        min_count: 目标区间下限。
        max_count: 目标区间上限。
    """
    if word_count < min_count:
        return f"偏短: {word_count} 字,低于下限 {min_count} 字"
    if word_count > max_count:
        return f"偏长: {word_count} 字,超过上限 {max_count} 字"
    return f"达标: {word_count} 字,落在 [{min_count}, {max_count}] 区间内"


# 挂给"精修"与"审校"两类 Agent:让模型能在改写前后各量一次,而不是凭感觉声称
# "已经改好了"。判定权仍在 stages.py 的强制判否逻辑手里,工具只提供数字。
STYLE_TOOLSET = ToolSet.from_funcs(
    "style_toolset", [style_metrics, style_violations, count_chinese_characters, check_length]
)
