"""月度创作风向 —— 从外部文件读取,与代码解耦。

平台每月发布一次官方推荐的热门创作方向,这类内容属于"写什么"
(development-guide.md §7 的分离约定),不应该混进 prompts.py;而是维护成
一份独立的文本文件(monthly_trend.md),运营方每月直接编辑/替换该文件即可
生效,不需要碰代码、不需要重新部署。
"""

from __future__ import annotations

import re
from pathlib import Path

from scenarios.essay.reference import load_reference_text

MONTHLY_TREND_PATH = Path(__file__).parent / "monthly_trend.md"

_SECTION_HEADING_RE = re.compile(r"^##[ \t]+(.+?)[ \t]*$", re.MULTILINE)


def load_monthly_trend() -> str:
    """读取当前的月度风向文本(见 reference.load_reference_text)。

    规划节点在文件不存在/为空时按无风向参考正常运行,不受影响。
    """
    return load_reference_text(MONTHLY_TREND_PATH)


def load_monthly_trend_options() -> list[dict[str, str]]:
    """把月度风向文本里以 "## 标题" 分隔的小节解析成可选方向列表。

    供前端"月度热点"页签展示——复用 load_monthly_trend() 同一份文件,不需要
    额外再维护一份结构化数据,运营方每月只替换 monthly_trend.md 一处即可让
    正文参考(给模型)和可选列表(给前端)同时生效。顶层 "# " 标题及其下方、
    第一个 "## " 之前的文字视为整体说明,不计入某个具体方向,不出现在结果里。
    """
    text = load_monthly_trend()
    if not text:
        return []
    headings = list(_SECTION_HEADING_RE.finditer(text))
    options = []
    for i, heading in enumerate(headings):
        title = heading.group(1).strip()
        start = heading.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        description = text[start:end].strip()
        options.append({"title": title, "description": description})
    return options
