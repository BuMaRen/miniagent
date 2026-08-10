"""端到端(假 LLMClient)测试 build_workflow() 的编排是否接对了 reads/writes/游标。

不调用真实 LLM,风格参照 tests/engine/test_loop.py:一个按脚本逐次返回 JSON
的假 LLMClient,断言节点被调用的次数、最终落到 state 里的值,以及跨轮传递
的反馈是否真的传到了下一轮的模型输入里。
"""

from __future__ import annotations

import json
import unittest
from unittest import mock

from engine.context import CheckpointRequest, RunContext
from llm.client import ChatResponse, LLMClient
from llm.image_client import ImageClient, ImageResult
from llm.message import Message
from state.backends.memory import InMemoryStateStore

from scenarios.essay.schemas.state import (
    BRIEF_PATH,
    COVER_BRIEF_PATH,
    COVER_IMAGE_PATH,
    DRAFT_PATH,
    META_PATH,
    PLAN_PATH,
    REVIEW_PATH,
    empty_state,
)
from scenarios.essay.workflow import build_workflow

PLAN_VALUE = {
    "protagonist_name": "武景年",
    "audience": "青年",
    "hook": "开篇冲突",
    "synopsis": "一段摘要",
    "chapters": [{"index": 1, "summary": "第一章", "target_word_count": 10, "is_climax": True}],
}

DRAFT_VALUE = [{"index": 1, "title": "第一章", "content": "一二三四五", "word_count": 0}]

META_VALUE = {
    "title": "重生后我惊艳全家",
    "blurb": "一段推广简介",
    "tags": {"genre": ["婚姻家庭"], "identity": ["赘婿"], "hook": ["重生", "打脸"]},
}

BRIEF_VALUE = {
    "synopsis": "测试用简介",
    "min_words": 1,
    "max_words": 1000,
    "category": "",
    "audience": "青年",
    "human_review": False,
    "cover_prompt": "",
    "generate_cover": True,
}


class ScriptedClient(LLMClient):
    """按脚本逐次返回结构化 JSON,用完重复最后一条(照抄 tests/engine/test_loop.py 的 _ScriptedCritic)。"""

    def __init__(self, script: list[dict]) -> None:
        self._script = list(script)
        self.calls = 0
        # 每次调用时,发给模型的最后一条消息内容(即 Agent.run 塞的
        # json.dumps(inputs)),供测试断言"这一轮真的看到了上一轮的反馈"。
        self.received: list[str] = []

    def chat(self, messages, tools=None, response_schema=None, **params) -> ChatResponse:
        self.calls += 1
        self.received.append(messages[-1].content or "")
        payload = self._script.pop(0) if len(self._script) > 1 else self._script[0]
        return ChatResponse(message=Message(role="assistant", content=json.dumps(payload, ensure_ascii=False)))


class FakeImageClient(ImageClient):
    def __init__(self) -> None:
        self.calls = 0
        self.received_prompts: list[str] = []

    def generate(self, prompt: str, **params) -> ImageResult:
        self.calls += 1
        self.received_prompts.append(prompt)
        return ImageResult(url="https://example.com/cover.png")


def _seed_state(store: InMemoryStateStore, **brief_overrides) -> None:
    store.load(empty_state())
    store.patch(BRIEF_PATH, {**BRIEF_VALUE, **brief_overrides})


class AcceptedOnFirstPassTests(unittest.TestCase):
    """审核第一次就通过:redraft_loop 应该靠 Breaker 直接短路,不白跑一轮。"""

    def test_redraft_is_skipped_when_first_review_passes(self) -> None:
        planning_client = ScriptedClient([{PLAN_PATH: PLAN_VALUE}])
        drafting_client = ScriptedClient([{DRAFT_PATH: DRAFT_VALUE}])
        review_client = ScriptedClient(
            [{DRAFT_PATH: DRAFT_VALUE, REVIEW_PATH: {"rejected": False, "feedback": ""}}]
        )
        meta_client = ScriptedClient([{META_PATH: META_VALUE}])
        cover_client = ScriptedClient([{COVER_BRIEF_PATH: "一段视觉描述"}])
        clients = {
            "planning": planning_client,
            "drafting": drafting_client,
            "review": review_client,
            "meta": meta_client,
            "cover": cover_client,
        }
        image_client = FakeImageClient()

        workflow = build_workflow(
            client_factory=lambda stage_name, model=None: clients[stage_name],
            image_client=image_client,
            human_review=False,
            generate_cover=True,
        )

        store = InMemoryStateStore()
        _seed_state(store, human_review=False)
        ctx = RunContext(state=store)

        workflow.run(ctx, {})

        self.assertEqual(planning_client.calls, 1)
        # drafting client 只被 first_draft 调用一次,redraft 因为 Breaker 短路
        # 完全没被调用;封面文案走独立的 cover client(不再复用 drafting)。
        self.assertEqual(drafting_client.calls, 1)
        self.assertEqual(review_client.calls, 1)
        self.assertEqual(meta_client.calls, 1)
        self.assertEqual(cover_client.calls, 1)
        self.assertEqual(image_client.calls, 1)

        self.assertFalse(store.get(REVIEW_PATH)["rejected"])
        self.assertEqual(store.get(PLAN_PATH)["protagonist_name"], "武景年")
        self.assertEqual(store.get(META_PATH)["title"], "重生后我惊艳全家")
        self.assertEqual(store.get(COVER_IMAGE_PATH)["url"], "https://example.com/cover.png")

    def test_cover_nodes_are_skipped_when_generate_cover_is_false(self) -> None:
        planning_client = ScriptedClient([{PLAN_PATH: PLAN_VALUE}])
        drafting_client = ScriptedClient([{DRAFT_PATH: DRAFT_VALUE}])
        review_client = ScriptedClient(
            [{DRAFT_PATH: DRAFT_VALUE, REVIEW_PATH: {"rejected": False, "feedback": ""}}]
        )
        meta_client = ScriptedClient([{META_PATH: META_VALUE}])
        image_client = FakeImageClient()

        # "cover" 故意不放进 clients:generate_cover=False 时 workflow 根本不该
        # 构造封面节点,client_factory 也就不该被以 "cover" 调用——如果调用了会
        # 直接 KeyError 而不是被默默忽略。meta 不受这个开关影响,始终要有,所以
        # 要放进 clients(否则 workflow 跑到 meta 节点会直接 KeyError)。
        clients = {
            "planning": planning_client,
            "drafting": drafting_client,
            "review": review_client,
            "meta": meta_client,
        }
        workflow = build_workflow(
            client_factory=lambda stage_name, model=None: clients[stage_name],
            image_client=image_client,
            human_review=False,
            generate_cover=False,
        )

        store = InMemoryStateStore()
        _seed_state(store, human_review=False, generate_cover=False)
        ctx = RunContext(state=store)

        workflow.run(ctx, {})

        self.assertEqual(meta_client.calls, 1)
        self.assertEqual(image_client.calls, 0)
        self.assertEqual(store.get(COVER_BRIEF_PATH), "")
        self.assertEqual(store.get(COVER_IMAGE_PATH), {"url": "", "note": ""})


class PlanningMonthlyTrendTests(unittest.TestCase):
    """规划节点应该把 trend.load_monthly_trend() 的结果注入模型输入,且每次
    运行都重新读取(不是构建期固定死的值),这样运营方替换 monthly_trend.md
    才能不改代码、不重启进程就生效。
    """

    def test_monthly_trend_is_injected_into_planning_input(self) -> None:
        planning_client = ScriptedClient([{PLAN_PATH: PLAN_VALUE}])
        drafting_client = ScriptedClient([{DRAFT_PATH: DRAFT_VALUE}])
        review_client = ScriptedClient([{DRAFT_PATH: DRAFT_VALUE, REVIEW_PATH: {"rejected": False, "feedback": ""}}])
        meta_client = ScriptedClient([{META_PATH: META_VALUE}])
        clients = {
            "planning": planning_client,
            "drafting": drafting_client,
            "review": review_client,
            "meta": meta_client,
        }
        workflow = build_workflow(
            client_factory=lambda stage_name, model=None: clients[stage_name],
            image_client=FakeImageClient(),
            human_review=False,
            generate_cover=False,
        )

        store = InMemoryStateStore()
        _seed_state(store, human_review=False, generate_cover=False)
        ctx = RunContext(state=store)

        with mock.patch("scenarios.essay.nodes.planning.load_monthly_trend", return_value="本月主打真假千金"):
            workflow.run(ctx, {})

        self.assertIn("本月主打真假千金", planning_client.received[0])


class RedraftLoopTests(unittest.TestCase):
    """第一次审核驳回(字数不达标),改稿一次后通过。

    审核放宽后 AI 不再对情节/爆点做打回判断(rejected/feedback 恒为
    False/""),打回只可能由系统的字数上下限判定触发,所以这里靠 brief 的
    min_words 制造一次字数不足的驳回。
    """

    def test_rejected_once_then_accepted(self) -> None:
        planning_client = ScriptedClient([{PLAN_PATH: PLAN_VALUE}])
        redraft_output = [{"index": 1, "title": "第一章", "content": "改过的更长正文内容", "word_count": 0}]
        drafting_client = ScriptedClient([{DRAFT_PATH: DRAFT_VALUE}, {DRAFT_PATH: redraft_output}])
        review_client = ScriptedClient(
            [
                {DRAFT_PATH: DRAFT_VALUE, REVIEW_PATH: {"rejected": False, "feedback": ""}},
                {DRAFT_PATH: redraft_output, REVIEW_PATH: {"rejected": False, "feedback": ""}},
            ]
        )
        meta_client = ScriptedClient([{META_PATH: META_VALUE}])
        cover_client = ScriptedClient([{COVER_BRIEF_PATH: "视觉描述"}])
        clients = {
            "planning": planning_client,
            "drafting": drafting_client,
            "review": review_client,
            "meta": meta_client,
            "cover": cover_client,
        }
        image_client = FakeImageClient()

        workflow = build_workflow(
            client_factory=lambda stage_name, model=None: clients[stage_name],
            image_client=image_client,
            human_review=False,
            generate_cover=True,
        )

        store = InMemoryStateStore()
        # DRAFT_VALUE 的正文只有 5 个字,min_words=6 让首轮因字数不足被系统打回。
        _seed_state(store, human_review=False, min_words=6)
        ctx = RunContext(state=store)

        workflow.run(ctx, {})

        self.assertEqual(drafting_client.calls, 2)  # first_draft + redraft
        self.assertEqual(review_client.calls, 2)
        self.assertEqual(cover_client.calls, 1)
        # redraft 读到了上一轮审核驳回的反馈(REVIEW_PATH 是真实 state 路径,
        # 不需要走 loop 游标——见 nodes/drafting.py 的注释)。
        self.assertIn("低于下限", drafting_client.received[1])
        self.assertFalse(store.get(REVIEW_PATH)["rejected"])
        self.assertEqual(store.get(DRAFT_PATH)[0]["content"], "改过的更长正文内容")


class PlanningCheckpointTests(unittest.TestCase):
    """human_review=True:情节规划被人工驳回一次后通过。"""

    def test_planning_rejected_once_then_approved(self) -> None:
        plan_v2 = {**PLAN_VALUE, "hook": "改过的爆点"}
        planning_client = ScriptedClient([{PLAN_PATH: PLAN_VALUE}, {PLAN_PATH: plan_v2}])
        drafting_client = ScriptedClient([{DRAFT_PATH: DRAFT_VALUE}])
        review_client = ScriptedClient(
            [{DRAFT_PATH: DRAFT_VALUE, REVIEW_PATH: {"rejected": False, "feedback": ""}}]
        )
        meta_client = ScriptedClient([{META_PATH: META_VALUE}])
        cover_client = ScriptedClient([{COVER_BRIEF_PATH: "视觉描述"}])
        clients = {
            "planning": planning_client,
            "drafting": drafting_client,
            "review": review_client,
            "meta": meta_client,
            "cover": cover_client,
        }
        image_client = FakeImageClient()

        checkpoint_answers = iter(
            [{"approved": False, "feedback": "爆点不够抓人"}, {"approved": True, "feedback": ""}]
        )
        received_requests: list[CheckpointRequest] = []

        def checkpoint_handler(request: CheckpointRequest) -> dict:
            received_requests.append(request)
            return next(checkpoint_answers)

        workflow = build_workflow(
            client_factory=lambda stage_name, model=None: clients[stage_name],
            image_client=image_client,
            human_review=True,
            generate_cover=True,
        )

        store = InMemoryStateStore()
        _seed_state(store, human_review=True)
        ctx = RunContext(state=store, checkpoint_handler=checkpoint_handler)

        workflow.run(ctx, {})

        self.assertEqual(planning_client.calls, 2)
        self.assertEqual(len(received_requests), 2)
        # 第二次规划的模型输入里,应该能看到人工驳回时给的反馈——证明
        # planning_checkpoint_loop 的游标(nodes/planning.py 的 reads)真的把
        # Checkpoint 的人工反馈传到了下一轮。
        self.assertIn("爆点不够抓人", planning_client.received[1])
        self.assertEqual(store.get(PLAN_PATH)["hook"], "改过的爆点")


if __name__ == "__main__":
    unittest.main()
