from state.schema import OneOf, StateSchema

_TEST_CASE = {
    "id": str,
    "title": str,
    "description": str,
    "preconditions": str,
    "steps": [str],
    "expected_results": [str],
    "priority": OneOf("high", "medium", "low"),
    "feedback": str,
}

_STATE_SCHEMA_NAME = "test_design_state"

DRAFT_KEY = "drafted_cases"
REVIEWED_KEY = "reviewed_cases"
DEPRECATED_KEY = "deprecated_cases"
REQUIREMENT_DOC_KEY = "requirement_doc"

DRAFT_PATH = f"{_STATE_SCHEMA_NAME}.{DRAFT_KEY}"
REVIEWED_PATH = f"{_STATE_SCHEMA_NAME}.{REVIEWED_KEY}"
DEPRECATED_PATH = f"{_STATE_SCHEMA_NAME}.{DEPRECATED_KEY}"
REQUIREMENT_DOC_PATH = f"{_STATE_SCHEMA_NAME}.{REQUIREMENT_DOC_KEY}"

# ------redraft 只编辑评审中的用例，通过与不通过的用例由需求方直接操作分类------

FIRST_DRAFT_OUTPUT_SCHEMA = StateSchema(
    "first_draft_output",
    {
        DRAFT_PATH: [_TEST_CASE],
    },
)

REDRAFT_OUTPUT_SCHEMA = StateSchema(
    "redraft_output",
    {
        DRAFT_PATH: [_TEST_CASE],
    },
)

REVIEW_OUTPUT_SCHEMA = StateSchema(
    "review_output",
    {
        DRAFT_PATH: [_TEST_CASE],
        REVIEWED_PATH: [_TEST_CASE],
        DEPRECATED_PATH: [_TEST_CASE],
    },
)

REQUIREMENT_PARSE_OUTPUT_SCHEMA = StateSchema(
    "requirement_parse_output",
    {
        REQUIREMENT_DOC_PATH: str,
    },
)

TEST_DESIGN_STATE_SCHEMA = StateSchema(
    _STATE_SCHEMA_NAME,
    {
        _STATE_SCHEMA_NAME: {
            REQUIREMENT_DOC_KEY: str,
            DRAFT_KEY: [_TEST_CASE],
            REVIEWED_KEY: [_TEST_CASE],
            DEPRECATED_KEY: [_TEST_CASE],
        }
    },
)


def empty_state() -> dict:
    """构造一份符合 schema 的空状态,作为一次新运行的起点。"""
    return TEST_DESIGN_STATE_SCHEMA.empty()
