"""short 场景的 StateSchema —— 一份短篇网文的"制作单"。

比 scenarios/novel 的故事圣经小一圈:短篇跨度短、人物少,不需要时间线与
世界观条目,伏笔也收敛成"爽点(payoff)"这一种 —— 短篇网文里真正要管理的
不是"埋了什么线索",而是"哪一节压下去、哪一节放出来"。

刻意分成两块互不覆盖的字段:

  · short_story.brief —— **用户填的设定**,由 brief.py 校验后原样存档,流程侧
    只读不写。它是"写什么"的唯一来源;流程侧的 prompt(prompts.py)里不出现
    任何题材内容,靠这一块注入。
  · 其余字段        —— **流程产出**(骨架/大纲/正文),用户不填。

这条边界就是需求里"用户输入的 prompt 与流程使用的 prompt 要分开"在状态层的
落点:换一个题材 = 换 short_story.brief,流程侧一个字都不用改。
"""

from __future__ import annotations

from state.schema import OneOf, StateSchema

# 用户设定(brief.yaml -> brief.parse_brief -> 这里)。字段清单与 brief.BRIEF_FIELDS
# 必须一一对应,brief.py 的模块 docstring 说明了为什么由那边做唯一定义。
BRIEF = {
    "premise": str,
    "setting": str,
    "protagonist": str,
    "antagonist": str,
    "hook_types": [str],
    "ending": str,
    "genre": str,
    "pov": str,
    "tone": str,
    "taboos": str,
    "extra": str,
    "target_word_count": [int],
    "section_count": int,
}

# 流程第一步(story_design)产出的故事骨架。
META = {
    "title": str,
    "logline": str,
    "one_line_hook": str,   # 开篇 300 字要抛出的那个钩子
    "core_conflict": str,
}

CHARACTER = {
    "id": str,
    "name": str,
    "role": OneOf("protagonist", "antagonist", "supporting"),
    "identity": str,
    "want": str,      # 他要什么
    "edge": str,      # 他的底牌/优势(主角的爽点从这里长出来)
    "flaw": str,      # 他的软肋(没有软肋就没有"先压后放")
    "arc": str,
}

# 爽点/爆点:短篇网文的骨架不是"情节点"而是"憋气-出气"的成对结构,所以
# 铺垫与回收的小节号是必填的结构信息,由 structure.outline_problems 校验。
# 刻意没有 status 字段:全篇的爽点是否真的兑现,由 section_critic 逐节对着
# payoff_note 判定,没有任何节点会去翻动这样一个标记 —— 加了就是一份永远
# 停在 "planned" 的死状态。
PAYOFF = {
    "id": str,
    "kind": str,              # 打脸/逆袭/揭底牌/身份反转…… 具体取值由内容决定,不枚举
    "setup_section": int,
    "payoff_section": int,
    "description": str,
}

SECTION = {
    "index": int,
    "title": str,
    "beat_summary": str,   # 本节要发生什么(大纲阶段写)
    "payoff_note": str,    # 本节承担的爽点/收尾钩子(大纲阶段写)
    "word_budget": int,    # 本节字数预算,各节相加须落在目标区间内
    "text": str,           # 正文(撰写/精修阶段写)
    "summary": str,        # 供后续小节引用的简短摘要,避免把全文塞进上下文
    "word_count": int,
    "status": OneOf("planned", "drafted", "polished"),
}

SHORT_STORY_DEFINITION = {
    "short_story": {
        "brief": BRIEF,
        "meta": META,
        "characters": [CHARACTER],
        "payoffs": [PAYOFF],
        "sections": [SECTION],
    },
    # 与 novel 场景同理:_loop / _foreach 的游标由引擎在首次写入时自建,
    # 不在这里声明(见 scenarios/novel/state_schema.py 末尾的说明)。
}

SHORT_STORY_SCHEMA = StateSchema(name="short_story", definition=SHORT_STORY_DEFINITION)


def empty_state() -> dict:
    """构造一份符合 schema 的空状态,作为一次新运行的起点。"""
    return SHORT_STORY_SCHEMA.empty()
