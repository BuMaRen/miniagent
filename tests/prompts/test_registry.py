"""PromptRegistry 的单测:登记、按名检索、以及各类使用错误。"""

import tempfile
import unittest
from pathlib import Path

from prompts.registry import PromptError, PromptRegistry, parse_ref


class ParseRefTests(unittest.TestCase):
    """"什么算引用"这条判断被 engine/spec.py 用来识别 stages.yaml 里的 "@名字"。"""

    def test_a_line_holding_only_a_name_is_a_reference(self):
        self.assertEqual(parse_ref("@style_guide"), "style_guide")
        self.assertEqual(parse_ref("   @style_guide  "), "style_guide")

    def test_inline_at_is_plain_text(self):
        self.assertIsNone(parse_ref("请联系 @张骞 确认"))
        self.assertIsNone(parse_ref("@style_guide 见上"))

    def test_double_at_is_an_escape_not_a_reference(self):
        self.assertIsNone(parse_ref("@@style_guide"))

    def test_non_identifier_names_are_plain_text(self):
        self.assertIsNone(parse_ref("@张骞"))


class PromptRegistryTests(unittest.TestCase):
    def setUp(self):
        self.registry = PromptRegistry()

    def test_register_and_get_plain_text(self):
        self.assertTrue(self.registry.register("greeting", "你好"))
        self.assertEqual(self.registry.get("greeting"), "你好")

    def test_duplicate_register_returns_false_and_keeps_the_first(self):
        self.registry.register("greeting", "你好")
        self.assertFalse(self.registry.register("greeting", "改写"))
        self.assertEqual(self.registry.get("greeting"), "你好")

    def test_get_does_not_expand_at_references(self):
        # 框架只登记、按名取回原文;一段提示词里出现的 "@其它名字" 原样保留,
        # 拼接/复用是场景方自己的事,不是 PromptRegistry 的职责。
        self.registry.register("style_guide", "【风格】现实主义")
        self.registry.register("stage", "开头\n@style_guide\n结尾")
        self.assertEqual(self.registry.get("stage"), "开头\n@style_guide\n结尾")

    def test_unregister_removes_a_name(self):
        self.registry.register("stage", "正文")
        self.registry.unregister("stage")
        with self.assertRaises(PromptError):
            self.registry.get("stage")

    def test_missing_prompt_reports_the_registered_ones(self):
        self.registry.register("style_guide", "【风格】现实主义")
        with self.assertRaises(PromptError) as caught:
            self.registry.get("nope")
        self.assertIn("style_guide", str(caught.exception))


class LoadDirTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        (self.dir / "style_guide.prompt").write_text("【风格】现实主义\n", encoding="utf-8")
        (self.dir / "stage.prompt").write_text("开头\n正文\n", encoding="utf-8")
        (self.dir / "notes.md").write_text("不是提示词", encoding="utf-8")
        self.registry = PromptRegistry()

    def test_names_come_from_the_file_stem_and_only_prompt_files_are_loaded(self):
        self.assertEqual(self.registry.load_dir(self.dir), ["stage", "style_guide"])
        self.assertEqual(self.registry.names(), ["stage", "style_guide"])

    def test_load_dir_registers_the_file_contents_verbatim(self):
        self.registry.load_dir(self.dir)
        self.assertEqual(self.registry.get("stage"), "开头\n正文\n")

    def test_load_dir_is_idempotent(self):
        self.registry.load_dir(self.dir)
        self.assertEqual(self.registry.load_dir(self.dir), [])
        self.assertEqual(self.registry.names(), ["stage", "style_guide"])

    def test_missing_dir_is_an_error(self):
        with self.assertRaises(PromptError):
            self.registry.load_dir(self.dir / "nope")


if __name__ == "__main__":
    unittest.main()
