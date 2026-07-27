"""故事圣经(Story Bible)的具体 StateSchema 实例。

字段设计对应 docs/story-bible-schema.md;引擎本身(state/schema.py)不含任何字段
语义,这里就是"场景方提供的那份 Schema"。

相对文档的一处务实扩展:`chapters[*]` 增加了 `text`(本章定稿正文)与
`word_count` 两个字段。文档原文只在 chapters 里保留 `draft_summary`(供后续
章节引用的摘要),理由是"只记会被引用的事实,避免状态膨胀"——但全文正文终究
要在某处落地,才能被"全文统稿"(3.9)与"最终输出"(3.10)阶段读到并写盘。
Loop/ForEach 都只把上一节点的输出向前传给下一节点、不做跨轮累积(见
engine/primitives/foreach.py 的模块 docstring),所以正文必须走 State Store
才能穿过 ForEach 的迭代边界——这里选择把它放进故事圣经而不是另开一份存储,
避免引入第二套"共享状态"概念。
"""

from __future__ import annotations

from state.schema import OneOf, Optional, StateSchema

# 以下几个子结构对象刻意不加下划线前缀:除了组装 STORY_BIBLE_DEFINITION,
# scenarios/novel/stages.py 还复用它们拼各 Stage 的 output_schema(见其模块
# docstring),因此是本模块对外的公共契约,而不是纯内部实现细节。
CHARACTER = {
    "id": str,
    "name": str,
    "role": OneOf("protagonist", "antagonist", "supporting"),
    "goal": str,
    "motivation": str,
    "flaw": str,
    "arc": str,
    "relationships": [{"target_id": str, "relation": str}],
    "status_log": [{"after_chapter": int, "state": str}],
}

WORLD_ENTRY = {
    "id": str,
    "name": str,
    "description": str,
    "established_in_chapter": int,
}

TIMELINE_EVENT = {
    "chapter": int,
    "event": str,
    "involved_characters": [str],
}

FORESHADOWING = {
    "id": str,
    "planted_in_chapter": int,
    "description": str,
    "payoff_chapter": Optional(int),
    "status": OneOf("planted", "resolved", "dropped"),
}

CHAPTER = {
    "index": int,
    "title": str,
    "beat_summary": str,
    "draft_summary": str,
    "text": str,
    "word_count": int,
    "status": OneOf("planned", "drafted", "reviewed"),
}

STORY_BIBLE_DEFINITION = {
    "story_bible": {
        "meta": {
            "title": str,
            "logline": str,
            "theme": str,
            "core_conflict": str,
            "structure_template": str,
            "target_word_count": [int],
            "genre": str,
            "pov": str,
            "tone": str,
        },
        "characters": [CHARACTER],
        "world": [WORLD_ENTRY],
        "timeline": [TIMELINE_EVENT],
        "foreshadowing": [FORESHADOWING],
        "chapters": [CHAPTER],
    },
    # ForEach 的游标(index/item)天然也落在 State 里、与 "story_bible" 平级
    # (见 engine/primitives/foreach.py 的默认路径 "_foreach.<name>.index/item")。
    # 这里特意不预先声明成 {} 或某个具体结构:empty_state() 若把它填成 {}, 后续
    # InMemoryStateStore._locate_parent 在其下新建 "chapter_loop" 这一层时看到的
    # 是"已存在的 dict"而非"缺失"，行为仍正确;但若声明成 ANY,_empty(ANY) 会
    # 填成 None,反而让 ForEach 第一次 patch 时在 None 上创建子层失败。所以干脆
    # 不在 definition 里声明这个键——它不属于故事圣经语义,由 ForEach 在首次写入
    # 时自己创建。
}

STORY_BIBLE_SCHEMA = StateSchema(name="story_bible", definition=STORY_BIBLE_DEFINITION)


def empty_state() -> dict:
    """构造一份符合 schema 的空故事圣经,作为一次新运行的起点。"""
    return STORY_BIBLE_SCHEMA.empty()
