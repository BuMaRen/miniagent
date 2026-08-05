import unittest

from engine.context import CheckpointRequest, LifecycleHooks, RunContext
from engine.primitives.checkpoint import Checkpoint
from engine.primitives.loop import Loop, LoopExceededError, OnExceed
from state.backends.memory import InMemoryStateStore
from state.schema import StateSchema

# 场景侧约定的判定字段名。极性是"真 = 还要再来一轮"(见 loop.py 的说明),
# 所以叫 needs_revision 而不是 passed。
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


def _continue_when(ctx, outputs):
    """判定谓词:直接对着刚跑完的节点的 outputs 求值,不经过 State。"""
    return outputs.get(FLAG, False)


class LoopPassesImmediatelyTests(unittest.TestCase):
    def test_single_round_when_nobody_asks_for_another(self):
        producer = _Producer("producer", _cursor())
        critic = _ScriptedCritic("critic", [{FLAG: False, "feedback": ""}])
        loop = Loop(name="loop", body=[producer, critic], continue_when=_continue_when)

        result = loop.run(_make_ctx(), {})

        self.assertEqual(producer.calls, 1)
        self.assertEqual(result["_loop"], {"name": "loop", "iterations": 1, "exhausted": False})
        # 返回值是 body 最后一个节点的产出,加上 _loop 记账。
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
        loop = Loop(
            name="loop", body=[producer, critic], continue_when=_continue_when, max_iterations=5
        )

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
        loop = Loop(name="loop", body=[producer, critic], continue_when=_continue_when)

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

        loop = Loop(name="loop", body=[_Spy(), critic], continue_when=_continue_when)
        loop.run(_make_ctx(), {"topic": "t"})

        self.assertEqual(seen, [{"topic": "t"}, {"topic": "t"}])

    def test_stale_flag_does_not_survive_into_the_next_round(self):
        """游标是整块替换而不是合并:上一轮判定为真的字段不能残留,否则死循环。"""
        producer = _Producer("producer", _cursor())
        critic = _ScriptedCritic(
            "critic",
            [{FLAG: True, "feedback": "x"}, {FLAG: False, "feedback": ""}],
        )
        loop = Loop(
            name="loop", body=[producer, critic], continue_when=_continue_when, max_iterations=5
        )

        result = loop.run(_make_ctx(), {})

        # 若合并,第二轮 producer 之后就会读到上一轮残留的 True 而重开,永远跑不完。
        self.assertEqual(result["_loop"]["iterations"], 2)

    def test_missing_flag_is_falsy_so_producer_does_not_trigger_restart(self):
        producer = _Producer("producer", _cursor())  # 输出里没有判定字段
        critic = _ScriptedCritic("critic", [{FLAG: False, "feedback": ""}])
        loop = Loop(name="loop", body=[producer, critic], continue_when=_continue_when)

        result = loop.run(_make_ctx(), {})

        self.assertEqual(len(critic.calls), 1)
        self.assertEqual(result["_loop"]["iterations"], 1)


class LoopShortCircuitTests(unittest.TestCase):
    """判定在每个节点之后而非整条 body 之后 —— 前一关没过就不必惊动后一关。"""

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
            body=[producer, ai_critic, human],
            continue_when=_continue_when,
        )

        result = loop.run(_make_ctx(), {})

        # 第一轮 AI 判否 -> human 没被执行;第二轮 AI 通过 -> human 才跑一次。
        self.assertEqual(human.calls, 1)
        self.assertEqual(result["_loop"]["iterations"], 2)


class LoopContinuePredicateTests(unittest.TestCase):
    """continue_when 是一个普通 Python 谓词(ctx, outputs) -> bool,不是状态路径
    字符串——这里专门验证"谓词可以是任意代码"这条能力,而不只是查一个固定字段。"""

    def test_predicate_can_read_ctx_state_not_just_outputs(self):
        """谓词拿到的是完整的 ctx,可以看 outputs 之外的状态,不局限于当前节点产出。

        注意:continue_when 在 body 里**每个**节点跑完后都会被调用一次,不只是
        "评审"那个节点——所以谓词要能安全地应付 producer(没有 score 字段)的
        outputs,不能假设自己只会被拿判定节点的产出来调用(这正是旧设计里
        "路径缺失时读到 None、判为假" 这条兜底在新设计下需要谓词自己负责的地方)。
        """
        producer = _Producer("producer", _cursor())
        critic = _ScriptedCritic("critic", [{"score": 1}, {"score": 3}])

        def continue_when(ctx, outputs):
            if "score" not in outputs:  # 不是评审节点的产出,不参与判定
                return False
            # 判定依据来自 ctx.state 里一个和 outputs 无关的字段,证明谓词不是
            # 被限定只能看"当前节点的 outputs"。
            ctx.state.patch("attempts", (ctx.state.get("attempts") or 0) + 1)
            return outputs["score"] < 3

        loop = Loop(name="loop", body=[producer, critic], continue_when=continue_when, max_iterations=5)
        ctx = _make_ctx()

        result = loop.run(ctx, {})

        self.assertEqual(result["_loop"]["iterations"], 2)
        self.assertEqual(ctx.state.get("attempts"), 2)

    def test_predicate_polarity_is_still_true_means_restart(self):
        """引擎侧极性不变:谓词返回 True 才重开一轮,场景可以在谓词内部自由取反
        (比如让上游节点产出 passed 而不是 needs_revision),不再被"裸路径不能取反"
        这条限制约束。"""
        producer = _Producer("producer", _cursor())
        critic = _ScriptedCritic("critic", [{"passed": False}, {"passed": True}])

        # 上游用的字段名是 passed(真=通过),谓词内部取反成"真=还要重开一轮";
        # producer 的 outputs 没有 passed 字段,get 的默认值 True 让它在取反后
        # 恒为 False,不会误触发重开一轮。
        continue_when = lambda ctx, outputs: not outputs.get("passed", True)
        loop = Loop(name="loop", body=[producer, critic], continue_when=continue_when)

        result = loop.run(_make_ctx(), {})

        self.assertEqual(result["_loop"]["iterations"], 2)
        self.assertTrue(result["passed"])


class LoopCursorHousekeepingTests(unittest.TestCase):
    def test_cursor_is_cleared_on_normal_exit(self):
        producer = _Producer("producer", _cursor())
        critic = _ScriptedCritic("critic", [{FLAG: False, "feedback": ""}])
        loop = Loop(name="loop", body=[producer, critic], continue_when=_continue_when)
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
            continue_when=_continue_when,
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
        loop = Loop(name="loop", body=[producer, critic], continue_when=_continue_when)

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
    直接当 body 里的一关:人工填的判定字段照样喂给是非器,驱动下一轮重写。"""

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

        loop = Loop(name="loop", body=[producer, human], continue_when=_continue_when)
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
            body=[producer, critic],
            continue_when=_continue_when,
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
        # 交给人的是最后一轮最后跑完的那个节点的产出 —— 短路时正是驳回它的意见。
        self.assertEqual(received[0].context["feedback"], "还是不行")

    def test_unknown_on_exceed_raises_value_error(self):
        loop = self._never_satisfied_loop(OnExceed.ACCEPT_LAST)
        loop.on_exceed = "bogus"  # bypass enum typing to hit the else branch
        with self.assertRaises(ValueError):
            loop.run(_make_ctx(), {})


if __name__ == "__main__":
    unittest.main()
