"""按真实的 workflow.yaml 走一遍"评审不通过 -> 重开一轮"的路径。

offline_demo 里所有 critic 都一次通过,所以它验证不到 Loop 真正重开一轮时的接线;
而这恰恰是最容易接错的地方:

  · 短路:AI critic 判否时,body 里排在它后面的人工确认(confirm_outline /
    chapter_pause)不该被执行 —— 不必拿一份 AI 都没过的草稿去打扰人;
  · 反馈跨轮:下一轮的生成节点必须能读到驳回它的那条 feedback,靠的是引擎发布的
    游标 _loop.<name>.last(见 stages.OUTLINE_LOOP_LAST_PATH),而不是 Loop 把
    feedback 塞进 inputs;
  · 人工与 AI 平权:人工填的 needs_revision 与 AI 的一样能驱动下一轮。

这里不 mock 引擎:用真实的 workflow.yaml、真实的 Loop/ForEach/Checkpoint,只把
LLM 换成按 Stage 名预置多条回复的脚本客户端。
"""

import json
import unittest
from typing import Any

from engine.context import CheckpointRequest, RunContext
from llm.client import ChatResponse, LLMClient
from llm.message import Message
from scenarios.novel.stages import NEEDS_REVISION_KEY, OUTLINE_LOOP_LAST_PATH
from scenarios.novel.state_schema import empty_state
from scenarios.novel.workflow import build_workflow
from state.backends.memory import InMemoryStateStore


def _final(payload: dict[str, Any]) -> ChatResponse:
    return ChatResponse(
        message=Message(role="assistant", content=json.dumps(payload, ensure_ascii=False))
    )


def _verdict(needs_revision: bool, feedback: str = "") -> ChatResponse:
    return _final({NEEDS_REVISION_KEY: needs_revision, "feedback": feedback})


_CHAPTER = {
    "index": 1,
    "title": "第一章",
    "beat_summary": "开场",
    "draft_summary": "摘要",
    "text": "正文",
    "word_count": 0,
    "status": "planned",
}


def _outline() -> dict[str, Any]:
    return {"story_bible.chapters": [dict(_CHAPTER)], "story_bible.foreshadowing": []}


def _chapter_draft() -> dict[str, Any]:
    return {
        "story_bible.chapters": [{**_CHAPTER, "status": "drafted"}],
        "chapter_index": 1,
        "chapter_text": "正文",
    }


class _ScriptedClient(LLMClient):
    """按顺序吐出预置回复,并记下每次调用时 system prompt 之外看到的 user 内容。"""

    def __init__(self, responses: list[ChatResponse]) -> None:
        self._responses = list(responses)
        self.seen_user_content: list[str] = []

    def chat(self, messages: list[Message], tools=None, **params: Any) -> ChatResponse:
        self.seen_user_content.append(
            "\n".join(m.content or "" for m in messages if m.role == "user")
        )
        if not self._responses:
            raise AssertionError("预置回复已用完(出现了未预期的额外调用)")
        return self._responses.pop(0)


class OutlineLoopRestartTests(unittest.TestCase):
    def setUp(self):
        # 大纲之后的所有阶段都给足回复,好让流程能一路跑到底。
        self.scripts = {
            "concept_expansion": [_final({"story_bible.meta": {}})],
            "character_world_design": [_final({"story_bible.meta": {"title": "书名"}})],
            "outline_generation": [_final(_outline()) for _ in range(3)],
            "outline_critic": [
                _verdict(True, "第三章节奏垮了"),  # 第 1 轮:AI 判否
                _verdict(False),                   # 第 2 轮:AI 通过,轮到人工
                _verdict(False),                   # 第 3 轮:AI 再次通过
            ],
            "chapter_drafting": [_final(_chapter_draft())],
            "chapter_critic": [_verdict(False)],
            # 统稿阶段照惯例回吐全量数组,这里保留章节审校已经推进到的 "reviewed"。
            "manuscript_assembly_polish": [
                _final(
                    {
                        "story_bible.chapters": [{**_CHAPTER, "status": "reviewed"}],
                        "story_bible.foreshadowing": [],
                    }
                )
            ],
        }
        self.clients: dict[str, _ScriptedClient] = {}
        self.checkpoints: list[str] = []

    def _factory(self, stage_name: str, _model: str | None) -> LLMClient:
        client = _ScriptedClient(self.scripts.get(stage_name, []))
        self.clients[stage_name] = client
        return client

    def _handler(self, human_answers: dict[str, list[dict[str, Any]]]):
        pending = {name: list(answers) for name, answers in human_answers.items()}

        def handler(request: CheckpointRequest) -> dict[str, Any]:
            self.checkpoints.append(request.name)
            answers = pending.get(request.name)
            if not answers:
                raise AssertionError(f"未预期的断点调用: {request.name}")
            return answers.pop(0)

        return handler

    def _run(self, human_answers):
        workflow = build_workflow(client_factory=self._factory)
        state = InMemoryStateStore(initial=empty_state())
        ctx = RunContext(state=state, checkpoint_handler=self._handler(human_answers))
        outputs = workflow.run(ctx, {"topic": "测试题材"})
        return state, outputs

    def test_ai_rejection_short_circuits_the_human_gate(self):
        state, _ = self._run(
            {
                # 第 2 轮人工判否,第 3 轮才放行 —— 人工总共只该被问两次:
                # 第 1 轮 AI 就判否了,那一轮不该惊动人工。
                "confirm_outline": [
                    {NEEDS_REVISION_KEY: True, "feedback": "主角动机再明确些"},
                    {NEEDS_REVISION_KEY: False, "feedback": ""},
                ],
                "chapter_pause": [{NEEDS_REVISION_KEY: False, "feedback": ""}],
            }
        )

        self.assertEqual(self.checkpoints.count("confirm_outline"), 2)
        # 大纲一共生成了 3 轮:AI 判否一次、人工判否一次,第 3 轮双双放行。
        self.assertEqual(len(self.clients["outline_generation"].seen_user_content), 3)
        # 流程确实走完了后面的章节与统稿阶段。
        self.assertEqual(state.get("story_bible.chapters")[0]["status"], "reviewed")

    def test_each_round_sees_the_previous_verdict_through_the_cursor(self):
        self._run(
            {
                "confirm_outline": [
                    {NEEDS_REVISION_KEY: True, "feedback": "主角动机再明确些"},
                    {NEEDS_REVISION_KEY: False, "feedback": ""},
                ],
                "chapter_pause": [{NEEDS_REVISION_KEY: False, "feedback": ""}],
            }
        )

        rounds = self.clients["outline_generation"].seen_user_content
        self.assertNotIn("第三章节奏垮了", rounds[0])  # 第一轮没有上一轮
        self.assertIn("第三章节奏垮了", rounds[1])  # AI 的意见
        self.assertIn("主角动机再明确些", rounds[2])  # 人工的意见,同样驱动重写
        # 两条意见都是经由游标这条状态路径送达的。
        self.assertIn(OUTLINE_LOOP_LAST_PATH, rounds[1])

    def test_cursor_is_cleared_once_the_loop_is_done(self):
        state, _ = self._run(
            {
                "confirm_outline": [
                    {NEEDS_REVISION_KEY: True, "feedback": "主角动机再明确些"},
                    {NEEDS_REVISION_KEY: False, "feedback": ""},
                ],
                "chapter_pause": [{NEEDS_REVISION_KEY: False, "feedback": ""}],
            }
        )

        # 不清的话,整章正文这类大对象会一直躺在持久化的状态快照里,
        # 也会泄漏给循环后面的节点。
        self.assertIsNone(state.get(OUTLINE_LOOP_LAST_PATH))
        self.assertIsNone(state.get("_loop.chapter_review_loop.last"))


if __name__ == "__main__":
    unittest.main()
