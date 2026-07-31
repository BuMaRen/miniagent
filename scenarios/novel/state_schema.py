"""故事圣经(Story Bible)的 StateSchema 加载入口。

字段声明本身在 state_schema.yaml 里(纯 YAML,DSL 见 state/schema.py 模块
docstring);把它编译成 definition、实例化 StateSchema 这件"构造胶水"已下沉到
框架的 StateSchema.from_yaml。这个模块只做两件事:加载那份 YAML,以及导出
NOVEL_TYPES——state_schema.yaml 里 types: 段声明的具名子结构表(CHARACTER/
WORLD_ENTRY/...)。这些片段同时出现在 story_bible 定义与各 Stage 的
output_schema 里(见 stages.py 模块 docstring),靠 load_types() 从同一份 YAML
借出,而不是各自在 Python/YAML 里重复声明,才能保证两处不会脱节。
"""

from __future__ import annotations

from pathlib import Path

from state.schema import StateSchema, load_types

STATE_SCHEMA_YAML_PATH = Path(__file__).with_name("state_schema.yaml")

STORY_BIBLE_SCHEMA = StateSchema.from_yaml(STATE_SCHEMA_YAML_PATH)
NOVEL_TYPES = load_types(STATE_SCHEMA_YAML_PATH)

CHARACTER = NOVEL_TYPES["character"]
WORLD_ENTRY = NOVEL_TYPES["world_entry"]
TIMELINE_EVENT = NOVEL_TYPES["timeline_event"]
FORESHADOWING = NOVEL_TYPES["foreshadowing"]
CHAPTER = NOVEL_TYPES["chapter"]


def empty_state() -> dict:
    """构造一份符合 schema 的空故事圣经,作为一次新运行的起点。"""
    return STORY_BIBLE_SCHEMA.empty()
