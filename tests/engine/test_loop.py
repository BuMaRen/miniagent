import unittest

from engine.context import CheckpointRequest, LifecycleHooks, RunContext
from engine.primitives.checkpoint import Checkpoint
from engine.primitives.continuer import Continuer
from engine.primitives.loop import Loop, LoopExceededError, OnExceed
from state.backends.memory import InMemoryStateStore
from state.schema import StateSchema

# 场景侧约定的判定字段名。极性是"真 = 还要再来一轮",所以叫 needs_revision
# 而不是 passed(见 continuer.py 与 loop.py 的说明)。
FLAG = "needs_revision"


class _Producer:
    """产出一版草稿;能读到游标里上一轮的评审意见就把它追加进草稿,证明反馈跨轮传到了。"""

    def __init__(self, name, cursor_path):
        self.name = name
        self._cursor_path = cursor_path
        self.calls = 0
        self.seen_feedback = []

    def run(self, ctx, inputs):
        self.calls += 1
        last = ctx.state.get(self._cursor_path) or {}
        feedback = last.get("feedback", "")
        self.seen_feedback.append(feedback)
        return {"draft": f"v{self.calls}", "carried_feedback": feedback}


class _ScriptedCritic:
    """按脚本逐轮给判定,用完后重复最后一条。"""

    def __init__(self, name, verdicts):
        self.name = name
        self._verdicts = list(verdicts)
        self.calls = []

    def run(self, ctx, inputs):
        self.calls.append(dict(inputs))
        verdict = self._verdicts.pop(0) if len(self._verdicts) > 1 else self._verdicts[0]
        return dict(verdict)


class _Recorder:
    """只记录自己被调用过几次 —— 用来验证短路时它没被执行。"""

    def __init__(self, name):
        self.name = name
        self.calls = 0

    def run(self, ctx, inputs):
        self.calls += 1
        return {"acked": True}


def _make_ctx(**kwargs):
    return RunContext(state=InMemoryStateStore(), **kwargs)


def _cursor(loop_name="loop"):
    return f"_loop.{loop_name}.last"


def _continuer(name="continuer"):
    """critic 之后放一个"重来一轮"节点:predicate 直接读它收到的 inputs(即
    critic 刚产出的 outputs)里的 FLAG——与旧版 continue_when 的判定逻辑等价,
    只是现在是场景方显式放进 body 的一个 Node,而不是引擎自动对每个节点问一遍。
    """
    return Continuer(name=name, predicate=lambda ctx, inputs: inputs.get(FLAG, False))


class LoopPassesImmediatelyTests(unittest.TestCase):
    def test_single_round_when_nobody_asks_for_another(self):
        producer = _Producer("producer", _cursor())
        critic = _ScriptedCritic("critic", [{FLAG: False, "feedback": ""}])
        loop = Loop(name="loop", body=[producer, critic, _continuer()])

        result = loop.run(_make_ctx(), {})

        self.assertEqual(producer.calls, 1)
        self.assertEqual(result["_loop"], {"name": "loop", "iterations": 1, "exhausted": False})
        # 返回值是 body 最后一个节点(continuer)透传的 outputs,加上 _loop 记账。
        self.assertFalse(result[FLAG])


class LoopRestartTests(unittest.TestCase):
    def test_body_reruns_from_the_top_until_flag_goes_false(self):
        producer = _Producer("producer", _cursor())
        critic = _ScriptedCritic(
            "critic",
            [
                {FLAG: True, "feedback": "改开头"},
                {FLAG: True, "feedback": "还得改结尾"},
                {FLAG: False, "feedback": ""},
            ],
        )
        loop = Loop(name="loop", body=[producer, critic, _continuer()], max_iterations=5)

        result = loop.run(_make_ctx(), {})

        self.assertEqual(producer.calls, 3)
        self.assertEqual(result["_loop"]["iterations"], 3)

    def test_previous_verdict_reaches_next_round_via_cursor(self):
        """跨轮唯一要传的东西(上一轮为什么没过)靠游标传,不靠 inputs 累积。"""
        producer = _Producer("producer", _cursor())
        critic = _ScriptedCritic(
            "critic",
            [
                {FLAG: True, "feedback": "改开头"},
                {FLAG: False, "feedback": ""},
            ],
        )
        loop = Loop(name="loop", body=[producer, critic, _continuer()])

        loop.run(_make_ctx(), {})

        # 第一轮没有上一轮,读到空;第二轮读到的是驳回它的那条意见。
        self.assertEqual(producer.seen_feedback, ["", "改开头"])

    def test_each_round_starts_from_the_same_inputs(self):
        """轮次之间不累积:第二轮的 body[0] 拿到的 inputs 和第一轮一模一样。"""
        producer = _Producer("producer", _cursor())
        critic = _ScriptedCritic(
            "critic",
            [{FLAG: True, "feedback": "x"}, {FLAG: False, "feedback": ""}],
        )
        seen = []

        class _Spy:
            name = "spy"

            def run(self, ctx, inputs):
                seen.append(dict(inputs))
                return producer.run(ctx, inputs)

        loop = Loop(name="loop", body=[_Spy(), critic, _continuer()])
        loop.run(_make_ctx(), {"topic": "t"})

        self.assertEqual(seen, [{"topic": "t"}, {"topic": "t"}])

    def test_stale_flag_does_not_survive_into_the_next_round(self):
        """游标是整块替换而不是合并:上一轮的产出不能残留进下一轮的游标读数。"""
        producer = _Producer("producer", _cursor())
        critic = _ScriptedCritic(
            "critic",
            [{FLAG: True, "feedback": "x"}, {FLAG: False, "feedback": ""}],
        )
        loop = Loop(name="loop", body=[producer, critic, _continuer()], max_iterations=5)

        result = loop.run(_make_ctx(), {})

        self.assertEqual(result["_loop"]["iterations"], 2)


class LoopShortCircuitTests(unittest.TestCase):
    """Continuer 放在某个节点之后而不是整条 body 之后 —— 前一关没过就不必惊动
    后一关(与 Breaker 的短路方式完全一致,见 breaker.py)。"""

    def test_later_body_nodes_are_skipped_when_an_earlier_one_rejects(self):
        producer = _Producer("producer", _cursor())
        ai_critic = _ScriptedCritic(
            "ai_critic",
            [
                {FLAG: True, "feedback": "AI 判否"},
                {FLAG: False, "feedback": ""},
            ],
        )
        human = _Recorder("human")
        loop = Loop(
            name="loop",
            body=[producer, ai_critic, _continuer(), human],
        )

        result = loop.run(_make_ctx(), {})

        # 第一轮 AI 判否 -> continuer 触发重开,human 没被执行;
        # 第二轮 AI 通过 -> continuer 透传,human 才跑一次。
        self.assertEqual(human.calls, 1)
        self.assertEqual(result["_loop"]["iterations"], 2)


class LoopCursorHousekeepingTests(unittest.TestCase):
    def test_cursor_is_cleared_on_normal_exit(self):
        producer = _Producer("producer", _cursor())
        critic = _ScriptedCritic("critic", [{FLAG: False, "feedback": ""}])
        loop = Loop(name="loop", body=[producer, critic, _continuer()])
        ctx = _make_ctx()

        loop.run(ctx, {})

        self.assertIsNone(ctx.state.get(_cursor()))

    def test_cursor_survives_a_checkpoint_pause_for_resume(self):
        """body 里的 Checkpoint 暂停时不清游标 —— 续跑时 body[0] 还要靠它读回意见。"""
        producer = _Producer("producer", _cursor())
        critic = _ScriptedCritic("critic", [{FLAG: False, "feedback": "看一眼"}])
        loop = Loop(
            name="loop",
            body=[producer, critic, Checkpoint(name="human_review")],
        )
        ctx = _make_ctx()  # 无 handler -> Checkpoint 抛 RuntimeError

        with self.assertRaises(Exception):
            loop.run(ctx, {})

        self.assertEqual(ctx.state.get(_cursor())["feedback"], "看一眼")


class LoopHooksTests(unittest.TestCase):
    def test_hooks_fire_per_iteration_with_pass_flag(self):
        calls = []
        hooks = LifecycleHooks(
            before_loop_iteration=lambda name, i: calls.append(("before", name, i)),
            after_loop_iteration=lambda name, i, passed: calls.append(("after", name, i, passed)),
        )
        producer = _Producer("producer", _cursor())
        critic = _ScriptedCritic(
            "critic",
            [{FLAG: True, "feedback": "x"}, {FLAG: False, "feedback": ""}],
        )
        loop = Loop(name="loop", body=[producer, critic, _continuer()])

        loop.run(_make_ctx(hooks=hooks), {})

        self.assertEqual(
            calls,
            [
                ("before", "loop", 0),
                ("after", "loop", 0, False),
                ("before", "loop", 1),
                ("after", "loop", 1, True),
            ],
        )


class LoopWithCheckpointInBodyTests(unittest.TestCase):
    """Checkpoint.run() 返回 inputs 与 resume_input 的合并结果,所以人工确认点可以
    直接当 body 里的一关:人工填的判定字段照样喂给后面的 Continuer,驱动下一轮重写。"""

    def test_human_rejection_drives_another_round(self):
        producer = _Producer("producer", _cursor())
        human = Checkpoint(
            name="human_review",
            resume_input_schema=StateSchema("review", {FLAG: bool, "feedback": str}),
        )
        answers = iter(
            [
                {FLAG: True, "feedback": "改一下开头"},
                {FLAG: False, "feedback": ""},
            ]
        )
        seen_context = []

        def handler(request):
            seen_context.append(request.context)
            return next(answers)

        loop = Loop(name="loop", body=[producer, human, _continuer()])
        result = loop.run(_make_ctx(checkpoint_handler=handler), {})

        self.assertEqual(producer.calls, 2)
        self.assertEqual(result["_loop"]["iterations"], 2)
        # 人工两次看到的都是当时正在被评审的那一版。
        self.assertEqual([c["draft"] for c in seen_context], ["v1", "v2"])


class LoopExceedTests(unittest.TestCase):
    def _never_satisfied_loop(self, on_exceed, max_iterations=2):
        producer = _Producer("producer", _cursor())
        critic = _ScriptedCritic("critic", [{FLAG: True, "feedback": "还是不行"}])
        return Loop(
            name="loop",
            body=[producer, critic, _continuer()],
            max_iterations=max_iterations,
            on_exceed=on_exceed,
        )

    def test_accept_last_returns_last_output_marked_exhausted(self):
        loop = self._never_satisfied_loop(OnExceed.ACCEPT_LAST, max_iterations=3)
        ctx = _make_ctx()

        result = loop.run(ctx, {})

        self.assertEqual(
            result["_loop"], {"name": "loop", "iterations": 3, "exhausted": True}
        )
        self.assertIsNone(ctx.state.get(_cursor()))

    def test_raise_raises_loop_exceeded_error(self):
        loop = self._never_satisfied_loop(OnExceed.RAISE)
        with self.assertRaises(LoopExceededError):
            loop.run(_make_ctx(), {})

    def test_escalate_without_handler_raises_runtime_error(self):
        loop = self._never_satisfied_loop(OnExceed.ESCALATE_TO_CHECKPOINT)
        with self.assertRaises(RuntimeError):
            loop.run(_make_ctx(), {})

    def test_escalate_with_handler_delegates_to_human(self):
        received: list[CheckpointRequest] = []

        def handler(request: CheckpointRequest):
            received.append(request)
            return {"draft": "human-approved"}

        loop = self._never_satisfied_loop(OnExceed.ESCALATE_TO_CHECKPOINT, max_iterations=2)
        result = loop.run(_make_ctx(checkpoint_handler=handler), {})

        self.assertEqual(result["draft"], "human-approved")
        self.assertTrue(result["_loop"]["exhausted"])
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].name, "loop")
        # 交给人的是最后一轮里、Continuer 触发重开前最后跑完的那个节点(critic)
        # 的产出 —— 正是驳回它的意见。
        self.assertEqual(received[0].context["feedback"], "还是不行")

    def test_unknown_on_exceed_raises_value_error(self):
        loop = self._never_satisfied_loop(OnExceed.ACCEPT_LAST)
        loop.on_exceed = "bogus"  # bypass enum typing to hit the else branch
        with self.assertRaises(ValueError):
            loop.run(_make_ctx(), {})


if __name__ == "__main__":
    unittest.main()
