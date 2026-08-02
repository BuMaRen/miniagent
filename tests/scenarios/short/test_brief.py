"""用户输入契约的单测。

这一层要钉住的是"设定不会被无声吞掉":拼错一个键、漏填必填项、把字数区间写成
一部长篇 —— 全都要在流程启动前炸出来,而不是等模型写出一篇跑题的东西才发现。
"""

import unittest
from pathlib import Path

from scenarios.short.brief import (
    BRIEF_FIELDS,
    DEFAULT_TARGET_WORD_COUNT,
    load_brief,
    parse_brief,
)
from scenarios.short.state_schema import BRIEF as BRIEF_SCHEMA_FIELDS

BRIEF_YAML = Path(__file__).resolve().parents[3] / "scenarios" / "short" / "brief.yaml"


class ParseBriefTests(unittest.TestCase):
    def test_only_premise_is_required(self):
        brief = parse_brief({"premise": "一个人要找回被偷走的名字"})
        self.assertEqual(brief["premise"], "一个人要找回被偷走的名字")
        self.assertEqual(brief["target_word_count"], DEFAULT_TARGET_WORD_COUNT)
        self.assertEqual(brief["hook_types"], [])
        self.assertEqual(brief["section_count"], 0)

    def test_missing_premise_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_brief({"genre": "都市"})
        with self.assertRaises(ValueError):
            parse_brief({"premise": "   "})

    def test_unknown_field_is_rejected_rather_than_ignored(self):
        with self.assertRaises(ValueError) as err:
            parse_brief({"premise": "x", "protagnist": "拼错的键"})
        self.assertIn("protagnist", str(err.exception))

    def test_hook_types_accepts_a_single_delimited_line(self):
        brief = parse_brief({"premise": "x", "hook_types": "打脸、逆袭,扮猪吃虎"})
        self.assertEqual(brief["hook_types"], ["打脸", "逆袭", "扮猪吃虎"])

    def test_word_count_out_of_supported_range_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_brief({"premise": "x", "target_word_count": [30000, 50000]})
        with self.assertRaises(ValueError):
            parse_brief({"premise": "x", "target_word_count": [9000, 8000]})

    def test_parse_is_idempotent(self):
        # input_parsing 会对宿主已经解析过的 brief 再解析一次(见 stages 的说明),
        # 所以幂等是这个流程接线成立的前提。
        once = parse_brief({"premise": "x"})
        self.assertEqual(parse_brief(once), once)


class BriefContractTests(unittest.TestCase):
    def test_fields_match_state_schema(self):
        # BRIEF_FIELDS 是唯一定义,state_schema.BRIEF 必须与它同步,否则
        # short_story.brief 会写进一个 schema 没声明的字段。
        self.assertEqual({f.name for f in BRIEF_FIELDS}, set(BRIEF_SCHEMA_FIELDS))

    def test_shipped_brief_yaml_is_valid(self):
        brief = load_brief(BRIEF_YAML)
        self.assertTrue(brief["premise"])
        self.assertEqual(set(brief), {f.name for f in BRIEF_FIELDS})


if __name__ == "__main__":
    unittest.main()
