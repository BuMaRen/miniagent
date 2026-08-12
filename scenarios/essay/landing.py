"""landing —— 把最终 State 落地成人可读/前端可用的交付物。

不是一个 workflow 里的 Stage,而是 run.py/httpserver 在 workflow.run() 成功
返回之后调用的一个纯函数,输入是 state_store.snapshot() 的完整快照。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scenarios.essay.schemas.state import TAG_DIMENSIONS

_STATE_KEY = "essay_state"


def write(snapshot: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    """把 snapshot 落地成 manuscript.md + story.json,返回结构化结果。

    Args:
        snapshot: state_store.snapshot() 的完整快照。
        output_dir: 产物输出目录,不存在会自动创建。

    Returns:
        结构化结果 dict(与写入 story.json 的内容一致,额外带上两个产物文件
        的路径),供 httpserver 的 /result 接口直接复用,不需要重新读盘。
    """
    essay = snapshot.get(_STATE_KEY, {}) or {}
    plan = essay.get("plan", {}) or {}
    draft = essay.get("draft", []) or []
    review = essay.get("review", {}) or {}
    meta = essay.get("meta", {}) or {}
    cover_brief = essay.get("cover_brief", "") or ""
    cover_image = essay.get("cover_image", {}) or {}

    output_dir.mkdir(parents=True, exist_ok=True)

    manuscript_path = output_dir / "manuscript.md"
    manuscript_path.write_text(_render_manuscript(plan, draft, cover_brief, meta), encoding="utf-8")

    total_words = sum(chapter.get("word_count", 0) for chapter in draft)
    # rejected 为 true 说明 redraft_loop 跑满 max_iterations 仍未通过审核
    # (development-guide.md §6 要求:跑满轮次仍不达标时,要把这个事实交代
    # 清楚,不能悄悄放过去)——这里显式标出来,供前端提示用户人工复核。
    result: dict[str, Any] = {
        "plan": plan,
        "chapters": sorted(draft, key=lambda c: c.get("index", 0)),
        "total_words": total_words,
        "review": review,
        "needs_manual_review": bool(review.get("rejected", False)),
        "meta": meta,
        "cover_brief": cover_brief,
        "cover_image": cover_image,
    }

    story_path = output_dir / "story.json"
    story_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    result["manuscript_path"] = str(manuscript_path)
    result["story_path"] = str(story_path)
    return result


def _render_manuscript(
    plan: dict[str, Any], draft: list[dict[str, Any]], cover_brief: str, meta: dict[str, Any]
) -> str:
    lines: list[str] = []
    # meta.title 是 meta 节点专门产出的标题,比"XX的故事"这种占位标题更贴合
    # 全篇实际看点;meta 节点始终执行,只有异常场景(如中途失败续跑到别的
    # 节点就失败了)才会缺失,这时退回旧的占位标题兜底。
    title = meta.get("title") or (f"{plan.get('protagonist_name', '')}的故事" if plan.get("protagonist_name") else "")
    if title:
        lines.append(f"# {title}\n")
    if meta.get("blurb"):
        lines.append(f"> {meta['blurb']}\n")
    tag_words = [word for dim in TAG_DIMENSIONS for word in _get_tags(meta, dim)]
    if tag_words:
        lines.append(f"标签:{' · '.join(tag_words)}\n")
    if meta.get("preview_ratio"):
        lines.append(f"建议试读比例:{meta['preview_ratio']:.0%}(超过此比例需看广告解锁)\n")
    if cover_brief:
        lines.append(f"> 封面文案:{cover_brief}\n")
    for chapter in sorted(draft, key=lambda c: c.get("index", 0)):
        chapter_title = chapter.get("title") or f"第 {chapter.get('index', '?')} 章"
        lines.append(f"## {chapter_title}\n")
        lines.append(chapter.get("content", "") + "\n")
    return "\n".join(lines)


def _get_tags(meta: dict[str, Any], dimension: str) -> list[str]:
    return (meta.get("tags") or {}).get(dimension) or []
