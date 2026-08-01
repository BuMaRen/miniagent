"""PromptRegistry 的单测:登记、按名检索、引用展开、占位符、以及各类使用错误。"""

import tempfile
import unittest
from pathlib import Path

from prompts.registry import PromptError, PromptRegistry, parse_ref


class ParseRefTests(unittest.TestCase):
    """"什么算引用"这条判断被 registry 与 engine/spec.py 共用,单独钉住。"""

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

    def test_reference_line_is_replaced_by_the_referenced_body(self):
        self.registry.register("style_guide", "【风格】现实主义")
        self.registry.register("stage", "开头\n@style_guide\n结尾")
        self.assertEqual(self.registry.get("stage"), "开头\n【风格】现实主义\n结尾")

    def test_references_expand_recursively(self):
        self.registry.register("inner", "最里层")
        self.registry.register("middle", "中间上\n@inner\n中间下")
        self.registry.register("outer", "@middle")
        self.assertEqual(self.registry.get("outer"), "中间上\n最里层\n中间下")

    def test_registration_order_does_not_matter(self):
        # 展开发生在 get 时,所以被引用的片段可以晚于引用它的提示词登记。
        self.registry.register("stage", "@style_guide")
        self.registry.register("style_guide", "【风格】现实主义")
        self.assertEqual(self.registry.get("stage"), "【风格】现实主义")

    def test_inline_at_is_left_alone(self):
        self.registry.register("stage", "邮件写 a@b.com,别写 @style_guide 这种")
        self.assertEqual(
            self.registry.get("stage"), "邮件写 a@b.com,别写 @style_guide 这种"
        )

    def test_double_at_escapes_to_a_literal_at(self):
        self.registry.register("stage", "@@style_guide")
        self.assertEqual(self.registry.get("stage"), "@style_guide")

    def test_placeholders_win_over_the_registry_and_fill_in_late_values(self):
        self.registry.register("stage", "输出格式:\n@output_schema_example")
        self.assertEqual(
            self.registry.get("stage", {"output_schema_example": "{...}"}),
            "输出格式:\n{...}",
        )

    def test_placeholders_reach_into_nested_references(self):
        self.registry.register("shared", "共享片段\n@marker")
        self.registry.register("stage", "@shared")
        self.assertEqual(self.registry.get("stage", {"marker": "填好了"}), "共享片段\n填好了")

    def test_render_expands_a_literal_body(self):
        self.registry.register("style_guide", "【风格】现实主义")
        self.assertEqual(self.registry.render("开头\n@style_guide"), "开头\n【风格】现实主义")

    def test_missing_prompt_reports_the_registered_ones(self):
        self.registry.register("style_guide", "【风格】现实主义")
        with self.assertRaises(PromptError) as caught:
            self.registry.get("nope")
        self.assertIn("style_guide", str(caught.exception))

    def test_missing_reference_is_reported_too(self):
        self.registry.register("stage", "@nope")
        with self.assertRaises(PromptError):
            self.registry.get("stage")

    def test_cycle_is_reported_with_the_chain(self):
        self.registry.register("a", "@b")
        self.registry.register("b", "@a")
        with self.assertRaises(PromptError) as caught:
            self.registry.get("a")
        self.assertIn("a -> b -> a", str(caught.exception))

    def test_self_reference_is_a_cycle(self):
        self.registry.register("a", "@a")
        with self.assertRaises(PromptError):
            self.registry.get("a")

    def test_raw_returns_the_unexpanded_body(self):
        self.registry.register("stage", "@style_guide")
        self.assertEqual(self.registry.raw("stage"), "@style_guide")


class LoadDirTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        (self.dir / "style_guide.prompt").write_text("【风格】现实主义\n", encoding="utf-8")
        (self.dir / "stage.prompt").write_text("开头\n@style_guide\n", encoding="utf-8")
        (self.dir / "notes.md").write_text("不是提示词", encoding="utf-8")
        self.registry = PromptRegistry()

    def test_names_come_from_the_file_stem_and_only_prompt_files_are_loaded(self):
        self.assertEqual(self.registry.load_dir(self.dir), ["stage", "style_guide"])
        self.assertEqual(self.registry.names(), ["stage", "style_guide"])

    def test_loaded_prompts_can_reference_each_other(self):
        self.registry.load_dir(self.dir)
        self.assertEqual(self.registry.get("stage"), "开头\n【风格】现实主义")

    def test_load_dir_is_idempotent(self):
        self.registry.load_dir(self.dir)
        self.assertEqual(self.registry.load_dir(self.dir), [])
        self.assertEqual(self.registry.names(), ["stage", "style_guide"])

    def test_missing_dir_is_an_error(self):
        with self.assertRaises(PromptError):
            self.registry.load_dir(self.dir / "nope")


if __name__ == "__main__":
    unittest.main()
