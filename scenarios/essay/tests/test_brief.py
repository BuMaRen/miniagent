import unittest

from scenarios.essay.brief import parse_brief


def _raw(**overrides):
    base = {"synopsis": "一个关于家庭的故事"}
    base.update(overrides)
    return base


class ParseBriefTests(unittest.TestCase):
    def test_fills_defaults(self) -> None:
        brief = parse_brief(_raw())
        self.assertEqual(brief["min_words"], 6000)
        self.assertEqual(brief["max_words"], 20000)
        self.assertEqual(brief["category"], "")
        self.assertEqual(brief["audience"], "")
        self.assertFalse(brief["human_review"])
        self.assertEqual(brief["cover_prompt"], "")
        self.assertFalse(brief["generate_cover"])

    def test_strips_synopsis(self) -> None:
        brief = parse_brief(_raw(synopsis="  带空格的简介  "))
        self.assertEqual(brief["synopsis"], "带空格的简介")

    def test_rejects_empty_synopsis(self) -> None:
        with self.assertRaises(ValueError):
            parse_brief(_raw(synopsis="   "))

    def test_rejects_min_words_below_floor(self) -> None:
        with self.assertRaises(ValueError):
            parse_brief(_raw(min_words=5999))

    def test_rejects_max_words_above_ceiling(self) -> None:
        with self.assertRaises(ValueError):
            parse_brief(_raw(max_words=20001))

    def test_rejects_min_greater_than_max(self) -> None:
        with self.assertRaises(ValueError):
            parse_brief(_raw(min_words=15000, max_words=8000))

    def test_accepts_boundary_values(self) -> None:
        brief = parse_brief(_raw(min_words=6000, max_words=20000))
        self.assertEqual(brief["min_words"], 6000)
        self.assertEqual(brief["max_words"], 20000)

    def test_rejects_non_bool_human_review(self) -> None:
        with self.assertRaises(ValueError):
            parse_brief(_raw(human_review="yes"))

    def test_rejects_non_bool_generate_cover(self) -> None:
        with self.assertRaises(ValueError):
            parse_brief(_raw(generate_cover="yes"))

    def test_accepts_generate_cover_true(self) -> None:
        brief = parse_brief(_raw(generate_cover=True))
        self.assertTrue(brief["generate_cover"])

    def test_rejects_non_dict_input(self) -> None:
        with self.assertRaises(ValueError):
            parse_brief("not a dict")  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
