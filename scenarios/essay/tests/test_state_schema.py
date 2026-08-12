import unittest

from state.schema import SchemaError
from scenarios.essay.schemas.state import (
    BRIEF_PATH,
    COVER_IMAGE_PATH,
    DRAFT_PATH,
    ESSAY_STATE_SCHEMA,
    META_PATH,
    PLAN_PATH,
    REVIEW_PATH,
    empty_state,
)


class EmptyStateTests(unittest.TestCase):
    def test_empty_state_validates(self) -> None:
        state = empty_state()
        ESSAY_STATE_SCHEMA.validate(state)

    def test_empty_state_shape(self) -> None:
        state = empty_state()["essay_state"]
        self.assertEqual(state["draft"], [])
        self.assertEqual(state["cover_image"], {"url": "", "note": ""})
        self.assertFalse(state["brief"]["human_review"])


class PathRoundTripTests(unittest.TestCase):
    def test_patch_and_read_back_each_declared_path(self) -> None:
        state = empty_state()
        state["essay_state"]["brief"] = {
            "synopsis": "x",
            "min_words": 6000,
            "max_words": 20000,
            "category": "",
            "audience": "",
            "human_review": True,
            "cover_prompt": "",
            "generate_cover": True,
        }
        state["essay_state"]["plan"] = {
            "protagonist_name": "武某",
            "audience": "青年",
            "hook": "开篇冲突",
            "synopsis": "摘要",
            "chapters": [{"index": 1, "summary": "s", "target_word_count": 1000, "is_climax": False}],
        }
        state["essay_state"]["draft"] = [{"index": 1, "title": "t", "content": "c", "word_count": 1}]
        ESSAY_STATE_SCHEMA.validate(state)

    def test_validate_path_matches_declared_paths(self) -> None:
        ESSAY_STATE_SCHEMA.validate_path(REVIEW_PATH, {"rejected": True, "feedback": "x"})
        ESSAY_STATE_SCHEMA.validate_path(COVER_IMAGE_PATH, {"url": "u", "note": "n"})
        ESSAY_STATE_SCHEMA.validate_path(
            META_PATH,
            {
                "title": "标题",
                "blurb": "简介",
                "tags": {
                    "category": ["婚姻家庭"],
                    "plot": ["打脸逆袭"],
                    "character": ["霸总"],
                    "emotion": ["爽文"],
                    "setting": ["豪门世家"],
                },
                "preview_ratio": 0.18,
            },
        )
        with self.assertRaises(SchemaError):
            ESSAY_STATE_SCHEMA.validate_path(REVIEW_PATH, {"rejected": "not a bool"})

    def test_paths_share_the_expected_top_level_name(self) -> None:
        for path in (BRIEF_PATH, PLAN_PATH, DRAFT_PATH, REVIEW_PATH, META_PATH, COVER_IMAGE_PATH):
            self.assertTrue(path.startswith("essay_state."))


if __name__ == "__main__":
    unittest.main()
