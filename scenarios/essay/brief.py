"""brief —— 用户输入的校验与默认值填充。

对应 requirement.md「前端详解」列出的字段:简介与字数上下限必选,属性
(类别/受众)、是否人工审核、是否生成封面、封面 prompt 可选。这里只做「这份
输入本身合不合法」的校验,不涉及任何流程/提示词逻辑(§7 的用户输入与流程
prompt 分离)。

校验失败立即抛 ValueError,而不是等跑到第一个节点才失败(development-guide.md
§8.1)——无论是 CLI 的 run.py 还是 httpserver,都应在真正发起任何 LLM 调用之前
调用一次 parse_brief。
"""

from __future__ import annotations

from typing import Any

MIN_WORDS_FLOOR = 6000
MAX_WORDS_CEILING = 20000


def parse_brief(raw: dict[str, Any]) -> dict[str, Any]:
    """校验并补全默认值,返回一份符合 schemas.state.BRIEF 结构的 dict。

    Args:
        raw: 未校验的原始输入(如 HTTP 请求体、CLI 读到的 JSON 文件)。

    Raises:
        ValueError: 任一字段不合法时,消息用中文说明具体哪里错了。
    """
    if not isinstance(raw, dict):
        raise ValueError("brief 必须是一个对象")

    synopsis = raw.get("synopsis")
    if not isinstance(synopsis, str) or not synopsis.strip():
        raise ValueError("synopsis(简介)不能为空")

    min_words = raw.get("min_words", MIN_WORDS_FLOOR)
    max_words = raw.get("max_words", MAX_WORDS_CEILING)
    if not isinstance(min_words, int) or isinstance(min_words, bool):
        raise ValueError("min_words 必须是整数")
    if not isinstance(max_words, int) or isinstance(max_words, bool):
        raise ValueError("max_words 必须是整数")
    if min_words < MIN_WORDS_FLOOR:
        raise ValueError(f"min_words 不能低于 {MIN_WORDS_FLOOR}")
    if max_words > MAX_WORDS_CEILING:
        raise ValueError(f"max_words 不能高于 {MAX_WORDS_CEILING}")
    if min_words > max_words:
        raise ValueError(f"min_words({min_words}) 不能大于 max_words({max_words})")

    category = raw.get("category", "")
    audience = raw.get("audience", "")
    cover_prompt = raw.get("cover_prompt", "")
    for field_name, value in (("category", category), ("audience", audience), ("cover_prompt", cover_prompt)):
        if not isinstance(value, str):
            raise ValueError(f"{field_name} 必须是字符串")

    human_review = raw.get("human_review", False)
    if not isinstance(human_review, bool):
        raise ValueError("human_review 必须是 true/false")

    # 默认不生成封面:封面是可选功能(不是每个故事都需要),且多跑一次图像
    # 生成节点意味着额外的模型调用开销,交给用户显式勾选打开。
    generate_cover = raw.get("generate_cover", False)
    if not isinstance(generate_cover, bool):
        raise ValueError("generate_cover 必须是 true/false")

    return {
        "synopsis": synopsis.strip(),
        "min_words": min_words,
        "max_words": max_words,
        "category": category.strip(),
        "audience": audience.strip(),
        "human_review": human_review,
        "cover_prompt": cover_prompt.strip(),
        "generate_cover": generate_cover,
    }
