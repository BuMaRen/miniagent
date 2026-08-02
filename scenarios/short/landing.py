"""把 State 里的成品落地成给人看的文件。

与 scenarios/novel 同样的分工:LLM 只产出结构化内容,磁盘 I/O 由宿主代码在拿到
ctx.state.snapshot() 之后统一处理。

产物里刻意包含 qa_report.json 与 story.md 末尾的"质检提示":这个场景没有人工
复核环节,交付时必须如实交代成品的成色 —— 哪几节字数没达标、还残留哪些文风
越界项,而不是把一份跑满轮次后被放行的稿子装成完美成品。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def land_output(
    state_snapshot: dict[str, Any], output_dir: Path, qa_report: dict[str, Any] | None = None
) -> dict[str, Path]:
    """把一份状态快照写成磁盘产物,返回 {产物标识: 路径}。

    产物:
      - story.md        成品正文(标题 + 各节),给读者看的那份
      - outline.md      大纲、角色与爽点设计,给作者复盘用
      - qa_report.json  终检报告(总字数/各节字数/残留的文风问题)
      - state.json      完整状态快照(便于调试与续跑)
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    story = state_snapshot.get("short_story", {})
    meta = story.get("meta") or {}
    brief = story.get("brief") or {}
    sections = sorted(story.get("sections") or [], key=lambda s: s.get("index", 0))

    written: dict[str, Path] = {}

    title = meta.get("title") or "(未命名)"
    parts = [f"# {title}", ""]
    if meta.get("logline"):
        parts += [f"> {meta['logline']}", ""]
    for section in sections:
        idx = section.get("index", 0)
        parts += [f"## {idx}. {section.get('title') or ''}".rstrip(), "", section.get("text") or "", ""]
    if qa_report:
        parts += ["---", "", _qa_footnote(qa_report), ""]
    story_path = output_dir / "story.md"
    story_path.write_text("\n".join(parts), encoding="utf-8")
    written["story"] = story_path

    outline_path = output_dir / "outline.md"
    outline_path.write_text(_render_outline(meta, brief, story, sections), encoding="utf-8")
    written["outline"] = outline_path

    if qa_report is not None:
        qa_path = output_dir / "qa_report.json"
        qa_path.write_text(json.dumps(qa_report, ensure_ascii=False, indent=2), encoding="utf-8")
        written["qa_report"] = qa_path

    state_path = output_dir / "state.json"
    state_path.write_text(json.dumps(state_snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    written["state"] = state_path

    return written


def _render_outline(
    meta: dict[str, Any], brief: dict[str, Any], story: dict[str, Any], sections: list[dict[str, Any]]
) -> str:
    lines = [f"# {meta.get('title') or '(未命名)'} · 创作档案", ""]
    lines += ["## 用户设定", ""]
    for key, value in brief.items():
        if value not in ("", [], None):
            lines.append(f"- **{key}**: {value}")
    lines += ["", "## 故事骨架", ""]
    for key in ("logline", "one_line_hook", "core_conflict"):
        if meta.get(key):
            lines.append(f"- **{key}**: {meta[key]}")

    lines += ["", "## 角色", ""]
    for character in story.get("characters") or []:
        lines.append(
            f"- **{character.get('name')}**({character.get('role')}):"
            f"想要 {character.get('want')};底牌 {character.get('edge')};软肋 {character.get('flaw')}"
        )

    lines += ["", "## 爽点设计", ""]
    for payoff in story.get("payoffs") or []:
        lines.append(
            f"- [{payoff.get('kind')}] 第{payoff.get('setup_section')}节埋 → "
            f"第{payoff.get('payoff_section')}节放:{payoff.get('description')}"
        )

    lines += ["", "## 分节大纲", ""]
    for section in sections:
        lines.append(
            f"- **第{section.get('index')}节 {section.get('title')}**"
            f"(预算 {section.get('word_budget')} 字 / 实际 {section.get('word_count')} 字)"
        )
        lines.append(f"  - 情节:{section.get('beat_summary')}")
        lines.append(f"  - 爽点/钩子:{section.get('payoff_note')}")
    return "\n".join(lines) + "\n"


def _qa_footnote(qa_report: dict[str, Any]) -> str:
    """成品末尾的一行质检提示 —— 没有人工复核,成色要写在明面上。"""
    total = qa_report.get("total_word_count", 0)
    low, high = (list(qa_report.get("target_word_count") or []) + [0, 0])[:2]
    in_range = qa_report.get("in_target_range")
    remaining = qa_report.get("remaining_style_violations") or []
    flagged = [
        str(s.get("index")) for s in qa_report.get("sections") or [] if s.get("style_violations")
    ]
    note = [f"*终检:全文 {total} 字,目标 [{low}, {high}],{'达标' if in_range else '未达标'}。*"]
    if flagged:
        note.append(f"*文风体检仍有越界项的小节:第 {'、'.join(flagged)} 节,建议人工过一遍。*")
    if remaining:
        note.append(f"*全文层面残留:{'; '.join(remaining)}*")
    return "\n".join(note)
