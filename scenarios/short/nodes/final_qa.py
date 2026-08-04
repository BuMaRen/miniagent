"""终检——纯函数,不需要 LLM。

没有人工复核环节,所以这一步的价值不是"再改一遍",而是"如实交代成品的成色":
总字数、各节字数、还残留哪些文风越界项。它写进 qa_report,由 landing.py 落盘,
谁拿到成品都能一眼看出哪几节需要人再看一下。
"""

from __future__ import annotations

from typing import Any

from engine.context import RunContext
from engine.stage import Stage

from scenarios.short.nodes.common import BRIEF_PATH, META_PATH, SECTIONS_PATH
from scenarios.short.toolsets.style import count_chinese_characters, style_metrics, style_violations


def final_qa_executor(ctx: RunContext, inputs: dict[str, Any]) -> dict[str, Any]:
    state = inputs.get("state", {})
    sections = state.get(SECTIONS_PATH) or []
    meta = state.get(META_PATH) or {}
    brief = state.get(BRIEF_PATH) or {}

    updated: list[dict[str, Any]] = []
    per_section: list[dict[str, Any]] = []
    total = 0
    for section in sorted(sections, key=lambda s: s.get("index", 0)):
        text = section.get("text") or ""
        word_count = count_chinese_characters(text)
        total += word_count
        updated.append({**section, "word_count": word_count})
        per_section.append(
            {
                "index": section.get("index"),
                "title": section.get("title"),
                "word_count": word_count,
                "word_budget": section.get("word_budget"),
                "style_violations": style_violations(text),
            }
        )

    min_words, max_words = (list(brief.get("target_word_count") or []) + [0, 0])[:2]
    full_text = "\n\n".join((s.get("text") or "") for s in updated)
    qa_report = {
        "title": meta.get("title", ""),
        "total_word_count": total,
        "section_count": len(updated),
        "target_word_count": [min_words, max_words],
        "in_target_range": (min_words <= total <= max_words) if max_words else None,
        "all_sections_have_text": all(s.get("text") for s in updated) if updated else False,
        "whole_text_style": style_metrics(full_text),
        "remaining_style_violations": style_violations(full_text),
        "sections": per_section,
    }
    return {SECTIONS_PATH: updated, "qa_report": qa_report}


def build_final_qa_stage() -> Stage:
    return Stage(
        name="final_qa",
        executor=final_qa_executor,
        reads=[SECTIONS_PATH, META_PATH, BRIEF_PATH],
        writes=[SECTIONS_PATH],
    )
