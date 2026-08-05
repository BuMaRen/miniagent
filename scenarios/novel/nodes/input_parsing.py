"""输入解析(3.1)—— 纯粹的默认值填充,用普通函数比用 LLM 更可靠也更省钱。"""

from __future__ import annotations

from typing import Any

from engine.context import RunContext
from engine.stage import Stage

from scenarios.novel.nodes.common import META_PATH

_DEFAULT_TARGET_WORD_COUNT = [8000, 20000]


def input_parsing_executor(ctx: RunContext, inputs: dict[str, Any]) -> dict[str, Any]:
    """校验/补全用户输入,产出故事圣经 meta 的初始骨架。"""
    topic = inputs.get("topic")
    if not topic:
        raise ValueError("input_parsing: 缺少必填字段 'topic'")

    meta = {
        "title": "",
        "logline": "",
        "theme": "",
        "core_conflict": "",
        "structure_template": inputs.get("structure_template") or "三幕式",
        "target_word_count": inputs.get("target_word_count") or _DEFAULT_TARGET_WORD_COUNT,
        "genre": inputs.get("genre") or "历史·现实主义",
        "pov": inputs.get("pov") or "第一人称",
        "tone": inputs.get("tone") or "沉稳克制,重考据与心理真实,非爽文",
    }
    return {META_PATH: meta, "topic": topic}


def build_input_parsing_stage() -> Stage:
    return Stage(
        name="input_parsing",
        executor=input_parsing_executor,
        writes=[META_PATH],
    )
