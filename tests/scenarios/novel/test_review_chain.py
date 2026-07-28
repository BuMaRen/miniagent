"""ReviewChain 是本场景自定义的 Node(不是引擎原语),所以测试也放在场景侧。

重点验证两件事:① 短路语义与 critic 契约校验;② 它确实能被当成一个普通 Node
直接塞进引擎的 Loop 的 critic 槽位——即"场景不改引擎也能扩展节点类型"这一
设计承诺是真的。
"""

import unittest

from engine.context import RunContext
from engine.primitives.loop import CriticContractError, Loop
from state.backends.memory import InMemoryStateStore

from scenarios.novel.review_chain import ReviewChain


class _ScriptedCritic:
    def __init__(self, name, verdict):
        self.name = name
        self.verdict = dict(verdict)
        self.calls = 0

    def run(self, ctx, inputs):
        self.calls += 1
        return dict(self.verdict)


def _ctx(**kwargs):
    return RunContext(state=InMemoryStateStore(), **kwargs)


class ReviewChainTests(unittest.TestCase):
    def test_all_pass_returns_last_verdict(self):
        ai = _ScriptedCritic("ai", {"passed": True, "feedback": ""})
        human = _ScriptedCritic("human", {"passed": True, "feedback": ""})
        chain = ReviewChain(name="review", critics=[ai, human])

        result = chain.run(_ctx(), {"draft": "x"})

        self.assertEqual(result, {"passed": True, "feedback": ""})
        self.assertEqual(ai.calls, 1)
        self.assertEqual(human.calls, 1)

    def test_first_failure_short_circuits(self):
        ai = _ScriptedCritic("ai", {"passed": False, "feedback": "AI 不通过"})
        human = _ScriptedCritic("human", {"passed": True, "feedback": ""})
        chain = ReviewChain(name="review", critics=[ai, human])

        result = chain.run(_ctx(), {"draft": "x"})

        self.assertEqual(result, {"passed": False, "feedback": "AI 不通过"})
        self.assertEqual(human.calls, 0, "AI 没过就不该去打扰人工")

    def test_second_failure_after_first_passes(self):
        ai = _ScriptedCritic("ai", {"passed": True, "feedback": ""})
        human = _ScriptedCritic("human", {"passed": False, "feedback": "人工不通过"})
        chain = ReviewChain(name="review", critics=[ai, human])

        result = chain.run(_ctx(), {"draft": "x"})

        self.assertEqual(result, {"passed": False, "feedback": "人工不通过"})

    def test_every_critic_sees_the_same_original_inputs(self):
        seen = []

        class _Recorder:
            name = "recorder"

            def run(self, ctx, inputs):
                seen.append(dict(inputs))
                return {"passed": True, "feedback": ""}

        ReviewChain(name="review", critics=[_Recorder(), _Recorder()]).run(
            _ctx(), {"draft": "x"}
        )

        self.assertEqual(seen, [{"draft": "x"}, {"draft": "x"}])

    def test_missing_passed_key_raises_contract_error(self):
        chain = ReviewChain(name="review", critics=[_ScriptedCritic("bad", {"feedback": "x"})])
        with self.assertRaises(CriticContractError):
            chain.run(_ctx(), {})

    def test_failing_without_feedback_raises_contract_error(self):
        chain = ReviewChain(name="review", critics=[_ScriptedCritic("bad", {"passed": False})])
        with self.assertRaises(CriticContractError):
            chain.run(_ctx(), {})


class ReviewChainAsLoopCriticTests(unittest.TestCase):
    """它没有继承任何引擎基类,仅凭 name + run 就能顶替 Loop 的 critic。"""

    def test_human_rejection_drives_reviser_then_whole_chain_reruns(self):
        class _Producer:
            name = "producer"

            def run(self, ctx, inputs):
                return {"draft": "v1"}

        class _Reviser:
            name = "reviser"

            def __init__(self):
                self.seen_feedback = []

            def run(self, ctx, inputs):
                self.seen_feedback.append(inputs.get("feedback"))
                return {"draft": inputs["draft"] + "!"}

        ai = _ScriptedCritic("ai", {"passed": True, "feedback": ""})

        human_answers = iter(
            [{"passed": False, "feedback": "改开头"}, {"passed": True, "feedback": ""}]
        )

        class _Human:
            name = "human"

            def run(self, ctx, inputs):
                return next(human_answers)

        reviser = _Reviser()
        chain = ReviewChain(name="review", critics=[ai, _Human()])
        loop = Loop(name="loop", producer=_Producer(), critic=chain, reviser=reviser)

        result = loop.run(_ctx(), {})

        self.assertEqual(result["draft"], "v1!")
        self.assertEqual(reviser.seen_feedback, ["改开头"])
        # 关键:修订稿重新过了一遍 AI critic,而不是绕开它直接回到人工。
        self.assertEqual(ai.calls, 2)


if __name__ == "__main__":
    unittest.main()
