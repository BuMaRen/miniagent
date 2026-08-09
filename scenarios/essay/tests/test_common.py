import unittest

from scenarios.essay.nodes.common import annotate_word_counts, count_chars, merge_rejection


class CountCharsTests(unittest.TestCase):
    def test_counts_non_whitespace_characters(self) -> None:
        self.assertEqual(count_chars("这是一段测试文字"), 8)

    def test_strips_whitespace_and_newlines(self) -> None:
        self.assertEqual(count_chars("一\n二 三\t四"), 4)

    def test_empty_and_none(self) -> None:
        self.assertEqual(count_chars(""), 0)
        self.assertEqual(count_chars(None), 0)


class AnnotateWordCountsTests(unittest.TestCase):
    def test_overwrites_word_count_and_returns_total(self) -> None:
        chapters = [
            {"content": "一二三", "word_count": 999},
            {"content": "四五", "word_count": -1},
        ]
        total = annotate_word_counts(chapters)
        self.assertEqual(chapters[0]["word_count"], 3)
        self.assertEqual(chapters[1]["word_count"], 2)
        self.assertEqual(total, 5)

    def test_empty_list(self) -> None:
        self.assertEqual(annotate_word_counts([]), 0)


class MergeRejectionTests(unittest.TestCase):
    def test_passes_when_within_bounds_and_ai_accepts(self) -> None:
        rejected, feedback = merge_rejection(
            ai_rejected=False, ai_feedback="", min_words=100, max_words=200, total_words=150
        )
        self.assertFalse(rejected)
        self.assertEqual(feedback, "")

    def test_rejects_when_below_min_words_even_if_ai_accepts(self) -> None:
        rejected, feedback = merge_rejection(
            ai_rejected=False, ai_feedback="", min_words=100, max_words=200, total_words=50
        )
        self.assertTrue(rejected)
        self.assertIn("低于下限", feedback)

    def test_rejects_when_above_max_words(self) -> None:
        rejected, feedback = merge_rejection(
            ai_rejected=False, ai_feedback="", min_words=100, max_words=200, total_words=250
        )
        self.assertTrue(rejected)
        self.assertIn("超过上限", feedback)

    def test_combines_word_count_and_ai_reasons(self) -> None:
        rejected, feedback = merge_rejection(
            ai_rejected=True, ai_feedback="爆点没有按时出现", min_words=100, max_words=200, total_words=50
        )
        self.assertTrue(rejected)
        self.assertIn("低于下限", feedback)
        self.assertIn("爆点没有按时出现", feedback)

    def test_ai_feedback_ignored_when_ai_rejected_is_false(self) -> None:
        rejected, feedback = merge_rejection(
            ai_rejected=False, ai_feedback="这条不该出现", min_words=100, max_words=200, total_words=150
        )
        self.assertFalse(rejected)
        self.assertNotIn("这条不该出现", feedback)


if __name__ == "__main__":
    unittest.main()
