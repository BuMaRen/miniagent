from state.schema import StateSchema

BRIEF = {
    "synopsis": str,
    "min_words": int,
    "max_words": int,
    "category": str,
    "audience": str,
    "human_review": bool,
    "cover_prompt": str,
    "generate_cover": bool,
}

CHAPTER_PLAN = {
    "index": int,
    "summary": str,
    "target_word_count": int,
    "is_climax": bool,
}

PLAN = {
    "protagonist_name": str,
    "audience": str,
    "hook": str,
    "synopsis": str,
    "chapters": [CHAPTER_PLAN],
}

CHAPTER = {
    "index": int,
    "title": str,
    "content": str,
    "word_count": int,
}

REVIEW = {
    "rejected": bool,
    "feedback": str,
}

COVER_IMAGE = {
    "url": str,
    "note": str,
}

# 与 tag_taxonomy.md 里的 "## 维度名" 分节一一对应,顺序即前端/manuscript
# 渲染标签时的展示顺序。
TAG_DIMENSIONS = ("category", "plot", "character", "emotion", "setting")

STORY_TAGS = {
    "category": [str],  # 主分类:婚姻家庭、女生生活……
    "plot": [str],  # 情节:追妻火葬场、真假千金……
    "character": [str],  # 角色:白月光、霸总……
    "emotion": [str],  # 情绪:甜宠、虐文……
    "setting": [str],  # 背景:家庭、职场……
}

STORY_META = {
    "title": str,
    "blurb": str,
    "tags": STORY_TAGS,
}

_STATE_SCHEMA_NAME = "essay_state"

BRIEF_KEY = "brief"
PLAN_KEY = "plan"
DRAFT_KEY = "draft"
REVIEW_KEY = "review"
META_KEY = "meta"
COVER_BRIEF_KEY = "cover_brief"
COVER_IMAGE_KEY = "cover_image"

BRIEF_PATH = f"{_STATE_SCHEMA_NAME}.{BRIEF_KEY}"
PLAN_PATH = f"{_STATE_SCHEMA_NAME}.{PLAN_KEY}"
DRAFT_PATH = f"{_STATE_SCHEMA_NAME}.{DRAFT_KEY}"
REVIEW_PATH = f"{_STATE_SCHEMA_NAME}.{REVIEW_KEY}"
META_PATH = f"{_STATE_SCHEMA_NAME}.{META_KEY}"
COVER_BRIEF_PATH = f"{_STATE_SCHEMA_NAME}.{COVER_BRIEF_KEY}"
COVER_IMAGE_PATH = f"{_STATE_SCHEMA_NAME}.{COVER_IMAGE_KEY}"

# ------ Stage 输出契约:key 是完整点分路径(与 Stage.writes / StateStore.patch 对齐)------

PLANNING_OUTPUT_SCHEMA = StateSchema("planning_output", {PLAN_PATH: PLAN})

DRAFT_OUTPUT_SCHEMA = StateSchema("draft_output", {DRAFT_PATH: [CHAPTER]})

REVIEW_OUTPUT_SCHEMA = StateSchema(
    "review_output",
    {
        DRAFT_PATH: [CHAPTER],
        REVIEW_PATH: REVIEW,
    },
)

META_OUTPUT_SCHEMA = StateSchema("meta_output", {META_PATH: STORY_META})

COVER_BRIEF_OUTPUT_SCHEMA = StateSchema("cover_brief_output", {COVER_BRIEF_PATH: str})

COVER_IMAGE_OUTPUT_SCHEMA = StateSchema("cover_image_output", {COVER_IMAGE_PATH: COVER_IMAGE})

# 情节规划人工审核 Checkpoint 的恢复输入契约。
APPROVAL_SCHEMA = StateSchema("planning_approval", {"approved": bool, "feedback": str})

ESSAY_STATE_SCHEMA = StateSchema(
    _STATE_SCHEMA_NAME,
    {
        _STATE_SCHEMA_NAME: {
            BRIEF_KEY: BRIEF,
            PLAN_KEY: PLAN,
            DRAFT_KEY: [CHAPTER],
            REVIEW_KEY: REVIEW,
            META_KEY: STORY_META,
            COVER_BRIEF_KEY: str,
            COVER_IMAGE_KEY: COVER_IMAGE,
        }
    },
)


def empty_state() -> dict:
    """构造一份符合 schema 的空状态,作为一次新运行的起点。"""
    return ESSAY_STATE_SCHEMA.empty()
