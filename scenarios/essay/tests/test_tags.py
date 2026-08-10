import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from scenarios.essay import tags


class LoadTagTaxonomyTests(unittest.TestCase):
    def _with_file(self, content: str | None) -> str:
        with TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "tag_taxonomy.md"
            if content is not None:
                path.write_text(content, encoding="utf-8")
            with mock.patch.object(tags, "TAG_TAXONOMY_PATH", path):
                return tags.load_tag_taxonomy()

    def test_missing_file_returns_empty_string(self) -> None:
        self.assertEqual(self._with_file(None), "")

    def test_returns_stripped_content(self) -> None:
        self.assertEqual(self._with_file("\n  ## 故事类型\n婚姻家庭  \n"), "## 故事类型\n婚姻家庭")

    def test_filters_out_maintenance_comment(self) -> None:
        content = "<!--\n维护说明\n-->\n## 爽点类型\n重生、系统流"
        self.assertEqual(self._with_file(content), "## 爽点类型\n重生、系统流")


if __name__ == "__main__":
    unittest.main()
