"""最终校验与输出(3.10)—— 字数/结构核对,纯函数,不需要 LLM。"""

from __future__ import annotations

from typing import Any

from engine.context import RunContext
from engine.stage import Stage

from scenarios.novel.nodes.common import CHAPTERS_PATH, META_PATH
from scenarios.novel.toolsets.qa import count_chinese_characters


def final_qa_executor(ctx: RunContext, inputs: dict[str, Any]) -> dict[str, Any]:
    """校验总字数/章节完整性,补全字数统计,产出呈现用的元数据。"""
    state = inputs.get("state", {})
    chapters = state.get(CHAPTERS_PATH) or []
    meta = dict(state.get(META_PATH) or {})

    updated_chapters = []
    total_words = 0
    for chapter in chapters:
        text = chapter.get("text", "")
        word_count = count_chinese_characters(text)
        total_words += word_count
        updated_chapters.append({**chapter, "word_count": word_count})

    min_count, max_count = (meta.get("target_word_count") or [0, 0])[:2] or (0, 0)
    qa_report = {
        "total_word_count": total_words,
        "chapter_count": len(chapters),
        "all_chapters_have_text": all(c.get("text") for c in chapters),
        "in_target_range": (min_count <= total_words <= max_count) if max_count else None,
        "has_title": bool(meta.get("title")),
    }

    return {
        CHAPTERS_PATH: updated_chapters,
        "qa_report": qa_report,
        "title": meta.get("title", ""),
        "logline": meta.get("logline", ""),
    }


def build_final_qa_stage() -> Stage:
    return Stage(
        name="final_qa",
        executor=final_qa_executor,
        reads=[CHAPTERS_PATH, META_PATH],
        writes=[CHAPTERS_PATH],
    )
