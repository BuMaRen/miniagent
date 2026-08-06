"""大纲/正文结构体检的单测,重点是 section_length_problem 的容差不对称。"""

import unittest

from scenarios.short.toolsets.structure import section_length_problem


class SectionLengthProblemTests(unittest.TestCase):
    def test_exactly_on_budget_is_fine(self):
        self.assertIsNone(section_length_problem(1000, 1000))

    def test_lower_bound_tolerance_is_tighter_than_upper_bound(self):
        # 默认 -10% / +25%:下限必须真的接近预算,上限留了更宽的余地。
        self.assertIsNone(section_length_problem(910, 1000))  # -9%,在容差内
        self.assertIsNotNone(section_length_problem(890, 1000))  # -11%,越界

        self.assertIsNone(section_length_problem(1240, 1000))  # +24%,在容差内
        self.assertIsNotNone(section_length_problem(1260, 1000))  # +26%,越界

    def test_under_budget_message_mentions_the_lower_bound(self):
        problem = section_length_problem(500, 1000)
        self.assertIsNotNone(problem)
        self.assertIn("低于预算", problem)
        self.assertIn("下限", problem)

    def test_over_budget_message_mentions_the_upper_bound(self):
        problem = section_length_problem(1500, 1000)
        self.assertIsNotNone(problem)
        self.assertIn("高于预算", problem)
        self.assertIn("上限", problem)

    def test_zero_budget_is_never_a_problem(self):
        # word_budget<=0 表示大纲阶段没给出预算,不该拿它去卡字数。
        self.assertIsNone(section_length_problem(0, 0))
        self.assertIsNone(section_length_problem(99999, 0))


if __name__ == "__main__":
    unittest.main()
