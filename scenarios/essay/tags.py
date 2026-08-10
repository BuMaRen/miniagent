"""标签词表 —— 从外部文件读取,与代码解耦(与 trend.py 同一套取舍)。

分类标签(故事类型/人物身份/爽点类型)的具体词表属于"写什么"
(development-guide.md §7 的分离约定),维护成一份独立文本文件
(tag_taxonomy.md),运营方随时可以整体替换成平台官方最新的标签体系,不需要
碰代码、不需要重新部署。
"""

from __future__ import annotations

from pathlib import Path

from scenarios.essay.reference import load_reference_text

TAG_TAXONOMY_PATH = Path(__file__).parent / "tag_taxonomy.md"


def load_tag_taxonomy() -> str:
    """读取当前的标签词表文本(见 reference.load_reference_text)。

    meta 节点在文件不存在/为空时按通用经验自行判断标签,不受影响。
    """
    return load_reference_text(TAG_TAXONOMY_PATH)
