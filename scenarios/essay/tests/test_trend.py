import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest import mock

from scenarios.essay import trend


def _with_trend_file(content: str | None, loader) -> Any:
    with TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / "monthly_trend.md"
        if content is not None:
            path.write_text(content, encoding="utf-8")
        with mock.patch.object(trend, "MONTHLY_TREND_PATH", path):
            return loader()


class LoadMonthlyTrendTests(unittest.TestCase):
    def _with_file(self, content: str | None) -> str:
        return _with_trend_file(content, trend.load_monthly_trend)

    def test_missing_file_returns_empty_string(self) -> None:
        self.assertEqual(self._with_file(None), "")

    def test_returns_stripped_content(self) -> None:
        self.assertEqual(self._with_file("\n  正文内容  \n"), "正文内容")

    def test_filters_out_multiline_html_comment(self) -> None:
        content = "<!--\n维护说明第一行\n维护说明第二行\n-->\n正文内容"
        self.assertEqual(self._with_file(content), "正文内容")

    def test_only_maintenance_comment_returns_empty_string(self) -> None:
        content = "<!-- 只有维护说明,没有正文 -->"
        self.assertEqual(self._with_file(content), "")


class LoadMonthlyTrendOptionsTests(unittest.TestCase):
    def _with_file(self, content: str | None) -> list[dict[str, str]]:
        return _with_trend_file(content, trend.load_monthly_trend_options)

    def test_missing_file_returns_empty_list(self) -> None:
        self.assertEqual(self._with_file(None), [])

    def test_no_sections_returns_empty_list(self) -> None:
        self.assertEqual(self._with_file("# 只有一个整体说明,没有任何 ## 小节"), [])

    def test_parses_each_section_into_title_and_description(self) -> None:
        content = (
            "# 整体说明,不应出现在结果里\n"
            "一些前言\n"
            "## 方向一\n"
            "方向一的描述,\n跨行也算。\n"
            "## 方向二\n"
            "方向二的描述。\n"
        )
        options = self._with_file(content)
        self.assertEqual(
            options,
            [
                {"title": "方向一", "description": "方向一的描述,\n跨行也算。"},
                {"title": "方向二", "description": "方向二的描述。"},
            ],
        )

    def test_section_without_body_has_empty_description(self) -> None:
        options = self._with_file("## 只有标题没有正文\n## 下一个方向\n内容")
        self.assertEqual(options[0], {"title": "只有标题没有正文", "description": ""})


if __name__ == "__main__":
    unittest.main()
