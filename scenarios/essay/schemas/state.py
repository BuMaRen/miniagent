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

STORY_TAGS = {
    "genre": [str],  # 故事类型:婚姻家庭、女生情感……
    "identity": [str],  # 人物身份:赘婿、豪门千金……
    "hook": [str],  # 爽点类型:重生、系统流……
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
