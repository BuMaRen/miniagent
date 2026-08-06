"""确定性文风体检的单测 —— 它是 short 场景在"没有人工复核"下的兜底关卡,
所以要钉住的是:被用户点名的三个 AI 痕迹(频繁短句、单句成段、描写零散)
确实会被判出来,而正常的中文叙述不会被误伤。
"""

import unittest

from scenarios.short.toolsets.style import (
    count_chinese_characters,
    split_sentences,
    style_metrics,
    style_violations,
)

# 一段"正常"的叙述:长短句错落,段落三句以上,细节编织在复合句里。
GOOD_PARAGRAPH = (
    "他把外卖箱靠在楼道墙角,借着声控灯忽明忽暗的光看清了那张被雨水泡软的收据,"
    "上面的日期正好是三年前他被赶出公司的那一天。收据边缘已经卷起,墨迹晕成一团,"
    "他却还是一眼认出了那串熟悉的项目编号,喉咙里像是被人塞进了一把沙子。"
    "楼上传来关门的声响,他把收据折好塞进胸口的内袋,顺手拽了拽头盔的带子。\n"
)

# 典型的 AI 腔:一句一段、清一色短句、没有一句把细节编织起来。
BAD_TEXT = "他睁开眼。\n\n天亮了。\n\n他起身。\n\n门开了。\n\n有人来了。\n\n他没有说话。\n\n风很冷。\n\n他走了出去。\n"


def _text_of(target_chars: int, paragraph: str = GOOD_PARAGRAPH) -> str:
    """把示例段落重复到指定汉字数,用于构造够长的样本。"""
    per = count_chinese_characters(paragraph)
    return paragraph * max(1, -(-target_chars // per))


class SplitSentencesTests(unittest.TestCase):
    def test_closing_quote_stays_with_its_sentence(self):
        # 句末标点后跟右引号时不能切出一个空壳句,否则每段对白都会被算成两句。
        sentences = split_sentences("“你到底是谁?”他问。")
        self.assertEqual(sentences, ["“你到底是谁?”他问。"])

    def test_multiple_sentences(self):
        self.assertEqual(len(split_sentences("他来了。她走了!谁在说话?")), 3)


class StyleMetricsTests(unittest.TestCase):
    def test_normal_prose_has_long_sentences_and_multi_sentence_paragraphs(self):
        m = style_metrics(_text_of(600))
        self.assertGreater(m["long_sentence_ratio"], 0.5)
        self.assertEqual(m["single_sentence_paragraph_ratio"], 0.0)
        self.assertEqual(m["char_count"], count_chinese_characters(_text_of(600)))

    def test_ai_flavored_text_is_all_short_single_sentence_paragraphs(self):
        m = style_metrics(BAD_TEXT)
        self.assertEqual(m["single_sentence_paragraph_ratio"], 1.0)
        self.assertEqual(m["short_sentence_ratio"], 1.0)
        self.assertEqual(m["long_sentence_ratio"], 0.0)


class StyleViolationsTests(unittest.TestCase):
    def test_normal_prose_passes(self):
        self.assertEqual(style_violations(_text_of(800)), [])

    def test_short_sample_skips_ratio_checks(self):
        # 不足 min_chars_for_check 时比率没有统计意义,不该判否(否则每段对白
        # 密集的开头都会被无意义地打回)。
        self.assertEqual(style_violations(BAD_TEXT), [])

    def test_long_ai_flavored_text_triggers_all_three_ratio_checks(self):
        problems = style_violations(BAD_TEXT * 12)
        self.assertEqual(len(problems), 3)
        joined = "".join(problems)
        self.assertIn("短句过多", joined)
        self.assertIn("单句成段过多", joined)
        self.assertIn("描写零散", joined)

    def test_cliche_density_is_reported_with_offenders(self):
        text = _text_of(500) + "他不禁仿佛似乎不禁仿佛似乎不禁仿佛似乎不禁仿佛似乎。\n"
        problems = style_violations(text)
        self.assertTrue(any("套话密度过高" in p for p in problems))


if __name__ == "__main__":
    unittest.main()
