"""整条流水线的接线单测:用假 LLM 跑完 workflow.yaml,不需要 API Key。

要钉住的是三件事:
  1. 结构通不通 —— 输入解析 -> 骨架 -> 大纲循环 -> 逐节(撰写/精修/审校)-> 终检,
     状态在各节点之间确实按 reads/writes 流动。
  2. 拼装归代码 —— 模型只吐本节 text/summary,整份 sections 由 executor 拼,
     不会因为"模型没回显前面几节"而丢正文。
  3. 内容与流程分离 —— 流程侧 prompt 里不出现用户 brief 里的任何内容。
"""

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from engine.context import RunContext
from llm.client import ChatResponse, LLMClient
from llm.message import Message
from state.backends.memory import InMemoryStateStore

from scenarios.short import prompts
from scenarios.short.brief import parse_brief
from scenarios.short.landing import land_output
from scenarios.short.state_schema import empty_state
from scenarios.short.toolsets.style import count_chinese_characters
from scenarios.short.workflow import build_workflow

_PARAGRAPH = (
    "他把外卖箱靠在楼道墙角,借着声控灯忽明忽暗的光看清了那张被雨水泡软的收据,"
    "上面的日期正好是三年前他被赶出公司的那一天。收据边缘已经卷起,墨迹晕成一团,"
    "他却还是一眼认出了那串熟悉的项目编号,喉咙里像是被人塞进了一把沙子。"
    "楼上传来关门的声响,他把收据折好塞进胸口的内袋,顺手拽了拽头盔的带子。\n"
)

_SECTION_BUDGET = 2100
_SECTION_COUNT = 4


def _text_for(budget: int) -> str:
    per = count_chinese_characters(_PARAGRAPH)
    return _PARAGRAPH * max(1, -(-budget // per))


class _FakeClient(LLMClient):
    """按节点名吐一份固定的结构化回复,并记下每次收到的消息,便于断言。"""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload
        self.calls: list[list[Message]] = []

    def chat(self, messages, tools=None, response_schema=None, **params) -> ChatResponse:
        self.calls.append(list(messages))
        return ChatResponse(
            message=Message(role="assistant", content=json.dumps(self._payload, ensure_ascii=False))
        )


class _SequencedFakeClient(LLMClient):
    """依次循环吐出一串回复(吐完从头再来),用来模拟"先判否、再判过"这类
    跨调用变化的场景 —— _FakeClient 每次都吐同一份,测不出这种时序行为。
    循环而不是吐完就卡在最后一份,是为了让 ForEach 里的每一节都独立经历一次
    完整的"判否 -> 判过",而不是只有第一节触发重开一轮。
    """

    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        self._payloads = payloads
        self.calls: list[list[Message]] = []

    def chat(self, messages, tools=None, response_schema=None, **params) -> ChatResponse:
        self.calls.append(list(messages))
        payload = self._payloads[(len(self.calls) - 1) % len(self._payloads)]
        return ChatResponse(
            message=Message(role="assistant", content=json.dumps(payload, ensure_ascii=False))
        )


def _payloads() -> dict[str, dict[str, Any]]:
    return {
        "story_design": {
            "title": "最后一单",
            "logline": "被抹掉署名的工程师在送外卖时撞见旧东家的把柄。",
            "one_line_hook": "他在会所门口按下快门的那一声。",
            "core_conflict": "他要拿回署名,对方要让他彻底消失。",
            "characters": [
                {
                    "id": "chenmo",
                    "name": "陈默",
                    "role": "protagonist",
                    "identity": "外卖骑手",
                    "want": "拿回属于自己的署名",
                    "edge": "他亲手留下的后门",
                    "flaw": "怕连累母亲",
                    "arc": "从躲避到正面出手",
                }
            ],
        },
        "outline_generation": {
            "sections": [
                {
                    "index": i,
                    "title": f"第{i}节",
                    "beat_summary": "局势推进一步,主角被摁住又找到一个缺口。",
                    "payoff_note": "以一个钩子收尾。",
                    "word_budget": _SECTION_BUDGET,
                }
                for i in range(1, _SECTION_COUNT + 1)
            ],
            "payoffs": [
                {
                    "id": "backdoor",
                    "kind": "揭底牌",
                    "setup_section": 1,
                    "payoff_section": 4,
                    "description": "后门在董事会现场被用出来。",
                }
            ],
        },
        "outline_critic": {"needs_revision": False, "feedback": ""},
        "section_drafting": {"text": _text_for(_SECTION_BUDGET), "summary": "本节摘要。"},
        "section_polish": {"text": _text_for(_SECTION_BUDGET), "revision_notes": "无。"},
        "section_critic": {"needs_revision": False, "feedback": ""},
    }


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.clients = {name: _FakeClient(payload) for name, payload in _payloads().items()}
        self.workflow = build_workflow(client_factory=lambda name, _model: self.clients[name])
        self.store = InMemoryStateStore()
        self.store.load(empty_state())
        self.brief = parse_brief(
            {"premise": "一个被抹掉署名的工程师撞见旧东家的把柄", "target_word_count": [8000, 10000]}
        )
        self.outputs = self.workflow.run(RunContext(state=self.store), dict(self.brief))

    def test_every_section_gets_text_assembled_by_code(self):
        sections = self.store.get("short_story.sections")
        self.assertEqual(len(sections), _SECTION_COUNT)
        for section in sections:
            self.assertTrue(section["text"], f"第{section['index']}节没有正文")
            self.assertEqual(section["summary"], "本节摘要。")
            self.assertEqual(section["word_count"], count_chinese_characters(section["text"]))
            self.assertEqual(section["status"], "polished")

    def test_brief_and_design_land_in_state(self):
        self.assertEqual(self.store.get("short_story.brief.premise"), self.brief["premise"])
        self.assertEqual(self.store.get("short_story.meta.title"), "最后一单")
        self.assertEqual(len(self.store.get("short_story.characters")), 1)

    def test_qa_report_reflects_the_finished_manuscript(self):
        report = self.outputs["qa_report"]
        self.assertEqual(report["section_count"], _SECTION_COUNT)
        self.assertTrue(report["all_sections_have_text"])
        self.assertTrue(report["in_target_range"], report)
        self.assertEqual(report["remaining_style_violations"], [])

    def test_each_section_passes_review_on_the_first_try(self):
        # 撰写固定一次(情节定死后不再重赌);精修/审校一旦过关就不再重来,
        # 假 Critic 首轮就判过,所以三者都恰好是一次。
        self.assertEqual(len(self.clients["section_drafting"].calls), _SECTION_COUNT)
        self.assertEqual(len(self.clients["section_polish"].calls), _SECTION_COUNT)
        self.assertEqual(len(self.clients["section_critic"].calls), _SECTION_COUNT)

    def test_outline_loop_passes_in_one_round_when_nothing_asks_for_revision(self):
        self.assertEqual(len(self.clients["outline_generation"].calls), 1)
        self.assertEqual(len(self.clients["outline_critic"].calls), 1)

    def test_landing_writes_the_expected_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            written = land_output(self.store.snapshot(), Path(tmp), self.outputs["qa_report"])
            self.assertEqual(set(written), {"story", "outline", "qa_report", "state"})
            story = written["story"].read_text(encoding="utf-8")
            self.assertIn("最后一单", story)
            self.assertIn("终检:全文", story)


class PolishRescuesAnAiFlavoredDraftTests(unittest.TestCase):
    """撰写节点写出一版典型 AI 腔时,精修节点会被调用,并把它救回来。"""

    def setUp(self):
        bad = "他睁开眼。\n\n天亮了。\n\n他起身。\n\n门开了。\n\n有人来了。\n\n他没有说话。\n\n风很冷。\n\n他走了出去。\n"
        payloads = _payloads()
        # 与预算同量级、但通篇短句一句一段:只会触发文风体检,不触发字数体检。
        payloads["section_drafting"] = {
            "text": bad * (_SECTION_BUDGET // count_chinese_characters(bad)),
            "summary": "本节摘要。",
        }
        self.clients = {name: _FakeClient(payload) for name, payload in payloads.items()}
        workflow = build_workflow(client_factory=lambda name, _model: self.clients[name])
        self.store = InMemoryStateStore()
        self.store.load(empty_state())
        brief = parse_brief({"premise": "随便一个题材"})
        self.outputs = workflow.run(RunContext(state=self.store), dict(brief))

    def test_polish_runs_once_per_section_and_its_text_is_what_gets_stored(self):
        self.assertEqual(len(self.clients["section_polish"].calls), _SECTION_COUNT)
        for section in self.store.get("short_story.sections"):
            self.assertEqual(section["status"], "polished")
            self.assertNotIn("他睁开眼。", section["text"])

    def test_the_manuscript_is_never_redrafted(self):
        # 一节固定一次撰写:救场由精修完成,而不是推倒重写。
        self.assertEqual(len(self.clients["section_drafting"].calls), _SECTION_COUNT)
        self.assertEqual(self.outputs["qa_report"]["remaining_style_violations"], [])


class ShortDraftIsRescuedByPolishTests(unittest.TestCase):
    """字数不达标时,精修节点被叫来补足 —— 正文层已经没有返工轮次可用。"""

    def setUp(self):
        payloads = _payloads()
        payloads["section_drafting"] = {"text": _text_for(300), "summary": "太短了。"}
        self.clients = {name: _FakeClient(payload) for name, payload in payloads.items()}
        workflow = build_workflow(client_factory=lambda name, _model: self.clients[name])
        self.store = InMemoryStateStore()
        self.store.load(empty_state())
        self.outputs = workflow.run(RunContext(state=self.store), parse_brief({"premise": "随便一个题材"}))

    def test_polish_is_called_with_the_length_problem_spelled_out(self):
        self.assertEqual(len(self.clients["section_polish"].calls), _SECTION_COUNT)
        payload = self.clients["section_polish"].calls[0][-1].content
        self.assertIn(prompts.KEY_AUTO_PROBLEMS, payload)
        self.assertIn("低于预算", payload)

    def test_polished_text_is_what_gets_stored(self):
        for section in self.store.get("short_story.sections"):
            self.assertEqual(section["word_count"], count_chinese_characters(section["text"]))
            self.assertGreater(section["word_count"], 300)

    def test_qa_report_tells_the_truth_about_what_was_let_through(self):
        # 精修救不回来时,成品照样交付,但终检必须如实写明 —— 没有人工复核,
        # 成色只能写在明面上。
        report = self.outputs["qa_report"]
        self.assertEqual(report["section_count"], _SECTION_COUNT)
        self.assertIn("in_target_range", report)


class SectionReviewLoopRetriesOnRevisionTests(unittest.TestCase):
    """section_review_loop 判否时应该从 section_polish 重开一轮,并把驳回理由
    带给下一次精修 —— 而不是原样放行、也不是重新撰写(情节不该被重赌)。
    """

    def setUp(self):
        payloads = _payloads()
        self.clients = {
            name: _FakeClient(payload) for name, payload in payloads.items() if name != "section_critic"
        }
        # 循环吐"判否(带具体意见)-> 判过",每一节都独立经历一次完整的返工。
        self.clients["section_critic"] = _SequencedFakeClient(
            [
                {"needs_revision": True, "feedback": "第二段的对话腔调太生硬,请重新组织。"},
                {"needs_revision": False, "feedback": ""},
            ]
        )
        workflow = build_workflow(client_factory=lambda name, _model: self.clients[name])
        self.store = InMemoryStateStore()
        self.store.load(empty_state())
        self.outputs = workflow.run(RunContext(state=self.store), parse_brief({"premise": "随便一个题材"}))

    def test_drafting_runs_once_but_polish_and_critic_run_twice_per_section(self):
        self.assertEqual(len(self.clients["section_drafting"].calls), _SECTION_COUNT)
        self.assertEqual(len(self.clients["section_polish"].calls), _SECTION_COUNT * 2)
        self.assertEqual(len(self.clients["section_critic"].calls), _SECTION_COUNT * 2)

    def test_first_polish_call_has_no_feedback_yet(self):
        first_call_payload = self.clients["section_polish"].calls[0][-1].content
        self.assertIn(f'"{prompts.KEY_FEEDBACK}": ""', first_call_payload)

    def test_second_polish_call_sees_the_critics_feedback(self):
        second_call_payload = self.clients["section_polish"].calls[1][-1].content
        self.assertIn("对话腔调太生硬", second_call_payload)

    def test_the_section_still_ends_up_polished(self):
        for section in self.store.get("short_story.sections"):
            self.assertEqual(section["status"], "polished")


class ContentAgnosticTests(unittest.TestCase):
    """流程侧 prompt 不许含用户内容 —— 这是本场景与 scenarios/novel 的根本区别。"""

    def test_workflow_prompts_do_not_embed_any_user_setting(self):
        shipped = Path(__file__).resolve().parents[3] / "scenarios" / "short" / "brief.yaml"
        brief = parse_brief(__import__("yaml").safe_load(shipped.read_text(encoding="utf-8")))
        flow_prompts = "\n".join(
            value for name, value in vars(prompts).items()
            if isinstance(value, str) and name.isupper()
        )
        for key, value in brief.items():
            for text in value if isinstance(value, list) else [value]:
                if isinstance(text, str) and len(text) >= 4:
                    self.assertNotIn(text, flow_prompts, f"brief.{key} 的内容泄漏进了流程 prompt")


if __name__ == "__main__":
    unittest.main()
