"""把落在 State Store 里的故事圣经"落地"成给人看的 Markdown/JSON 文件。

刻意不让 LLM 自己写文件:final_qa Stage(见 stages.py)只产出结构化的校验
结果,真正的磁盘 I/O 由宿主代码(run.py / offline_demo.py)在拿到
ctx.state.snapshot() 之后统一处理——职责边界清晰,也方便单测断言产物内容。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def land_output(state_snapshot: dict[str, Any], output_dir: Path) -> dict[str, Path]:
    """把一份故事圣经快照写成磁盘产物,返回 {产物标识: 路径}。

    产物:
      - story_bible.json      完整状态快照(便于调试/续跑)
      - chapters/chapter_XX.md 每章单独一个文件
      - manuscript.md          全书合并(标题 + 简介 + 各章正文)
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    bible = state_snapshot.get("story_bible", {})
    meta = bible.get("meta") or {}
    chapters = bible.get("chapters") or []

    written: dict[str, Path] = {}

    bible_path = output_dir / "story_bible.json"
    bible_path.write_text(
        json.dumps(state_snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    written["story_bible"] = bible_path

    chapters_dir = output_dir / "chapters"
    chapters_dir.mkdir(exist_ok=True)

    title = meta.get("title") or "(未命名)"
    manuscript_parts = [f"# {title}", ""]
    if meta.get("logline"):
        manuscript_parts += [f"> {meta['logline']}", ""]

    for chapter in sorted(chapters, key=lambda c: c.get("index", 0)):
        idx = chapter.get("index", 0)
        chapter_title = chapter.get("title") or f"第{idx}章"
        text = chapter.get("text") or ""
        chapter_path = chapters_dir / f"chapter_{idx:02d}.md"
        chapter_path.write_text(f"# 第{idx}章 {chapter_title}\n\n{text}\n", encoding="utf-8")
        written[f"chapter_{idx:02d}"] = chapter_path
        manuscript_parts += [f"## 第{idx}章 {chapter_title}", "", text, ""]

    manuscript_path = output_dir / "manuscript.md"
    manuscript_path.write_text("\n".join(manuscript_parts), encoding="utf-8")
    written["manuscript"] = manuscript_path

    return written
