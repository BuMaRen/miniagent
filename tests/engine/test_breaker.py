import unittest

from bumaren_agent_workflow.engine.context import LifecycleHooks, RunContext
from bumaren_agent_workflow.engine.primitives.breaker import Breaker, LoopBreak
from bumaren_agent_workflow.engine.primitives.continuer import Continuer
from bumaren_agent_workflow.engine.primitives.foreach import ForEach
from bumaren_agent_workflow.engine.primitives.loop import Loop
from bumaren_agent_workflow.engine.primitives.sequence import Sequence
from bumaren_agent_workflow.state.backends.memory import InMemoryStateStore


def _ctx(**kwargs):
    kwargs.setdefault("state", InMemoryStateStore())
    return RunContext(**kwargs)


def _needs_revision_continuer(name="continuer"):
    """critic 之后放一个"重来一轮"节点,判定逻辑读它收到的 inputs 里的
    needs_revision 字段(见 test_loop.py 的 _continuer 与 continuer.py)。"""
    return Continuer(name=name, predicate=lambda ctx, inputs: inputs.get("needs_revision", False))


class BreakerStandaloneTests(unittest.TestCase):
    def test_passthrough_when_predicate_is_false(self):
        breaker = Breaker(name="stop", predicate=lambda ctx, inputs: False)
        result = breaker.run(_ctx(), {"x": 1})
        self.assertEqual(result, {"x": 1})

    def test_raises_loop_break_with_current_outputs_when_predicate_is_true(self):
        breaker = Breaker(name="stop", predicate=lambda ctx, inputs: inputs.get("done"))
        with self.assertRaises(LoopBreak) as ctx_mgr:
            breaker.run(_ctx(), {"done": True, "x": 1})
        self.assertEqual(ctx_mgr.exception.name, "stop")
        self.assertEqual(ctx_mgr.exception.outputs, {"done": True, "x": 1})


class _AlwaysAsksForAnotherRound:
    """跑到就要求重开一轮(后面接的 Continuer 判定会为真)的节点,用来证明
    Breaker 能在它之前把它整个截断,不让它有机会要求重开。"""

    name = "critic"

    def __init__(self):
        self.calls = 0

    def run(self, ctx, inputs):
        self.calls += 1
        return {**inputs, "needs_revision": True}


class BreakerInLoopTests(unittest.TestCase):
    def test_breaker_preempts_a_later_node_that_would_ask_to_continue(self):
        # body = [breaker, critic, continuer]:critic 若跑到、continuer 判定它的
        # 产出就会要求重开一轮,但 breaker 排在最前面且第一轮就判定为真——critic
        # 根本不会被执行,循环以 breaker 触发时的 outputs 立即结束,而不是被
        # continuer 拖着重开。
        critic = _AlwaysAsksForAnotherRound()
        breaker = Breaker(name="budget", predicate=lambda ctx, inputs: True)
        loop = Loop(
            name="loop",
            body=[breaker, critic, _needs_revision_continuer()],
            max_iterations=5,
        )
        ctx = _ctx()

        result = loop.run(ctx, {"topic": "t"})

        self.assertEqual(critic.calls, 0)
        self.assertEqual(result["_loop"], {"name": "loop", "iterations": 1, "exhausted": False})
        self.assertEqual(result["topic"], "t")
        # 游标照常被清理,和正常通过时一致。
        self.assertIsNone(ctx.state.get("_loop.loop.last"))

    def test_hooks_fire_with_passed_true_on_break(self):
        calls = []
        hooks = LifecycleHooks(
            after_loop_iteration=lambda name, i, passed: calls.append((name, i, passed))
        )
        breaker = Breaker(name="stop", predicate=lambda ctx, inputs: True)
        loop = Loop(name="loop", body=[breaker])

        loop.run(_ctx(hooks=hooks), {})

        self.assertEqual(calls, [("loop", 0, True)])

    def test_breaker_only_breaks_after_a_few_iterations_when_predicate_says_so(self):
        # 前两轮 breaker 不触发,critic 跑到、continuer 要求重开;第三轮 breaker
        # 先一步触发,critic 那一轮根本没机会跑,循环以 3 轮收尾。
        counter = {"n": 0}

        def predicate(ctx, inputs):
            counter["n"] += 1
            return counter["n"] >= 3

        critic = _AlwaysAsksForAnotherRound()
        breaker = Breaker(name="budget", predicate=predicate)
        loop = Loop(
            name="loop",
            body=[breaker, critic, _needs_revision_continuer()],
            max_iterations=10,
        )

        result = loop.run(_ctx(), {})

        self.assertEqual(critic.calls, 2)
        self.assertEqual(result["_loop"]["iterations"], 3)


class BreakerInForEachTests(unittest.TestCase):
    def test_breaker_stops_remaining_items(self):
        seen = []

        class _Track:
            name = "track"

            def run(self, ctx, inputs):
                item = ctx.state.get("_foreach.fe.item")
                seen.append(item)
                return {}

        breaker = Breaker(name="stop_early", predicate=lambda ctx, inputs: seen[-1] == "two")
        body = Sequence(name="body", nodes=[_Track(), breaker])
        state = InMemoryStateStore(initial={"chapters": ["one", "two", "three", "four"]})
        fe = ForEach(name="fe", items_path="chapters", body=body)

        result = fe.run(_ctx(state=state), {})

        self.assertEqual(seen, ["one", "two"])  # "three"/"four" 不再处理
        self.assertEqual(result, {"iterations": 2, "items_path": "chapters", "broken": True})
        self.assertEqual(state.get("_foreach.fe.index"), 2)

    def test_no_broken_key_when_predicate_never_fires(self):
        class _Track:
            name = "track"

            def run(self, ctx, inputs):
                return {}

        breaker = Breaker(name="never", predicate=lambda ctx, inputs: False)
        body = Sequence(name="body", nodes=[_Track(), breaker])
        state = InMemoryStateStore(initial={"chapters": ["one", "two"]})
        fe = ForEach(name="fe", items_path="chapters", body=body)

        result = fe.run(_ctx(state=state), {})

        self.assertEqual(result, {"iterations": 2, "items_path": "chapters"})
        self.assertNotIn("broken", result)


class BreakerNestingTests(unittest.TestCase):
    def test_breaker_inside_inner_loop_only_breaks_the_inner_loop(self):
        """ForEach.body 里套一个 Loop,Breaker 在 Loop.body 里——只应该终止这个
        内层 Loop,外层 ForEach 继续处理下一个 item(验证"只断最近一层")。"""
        inner_runs = []

        class _InnerProducer:
            name = "inner"

            def run(self, ctx, inputs):
                item = ctx.state.get("_foreach.fe.item")
                inner_runs.append(item)
                return {}

        breaker = Breaker(name="inner_stop", predicate=lambda ctx, inputs: True)
        inner_loop = Loop(name="inner_loop", body=[_InnerProducer(), breaker])
        state = InMemoryStateStore(initial={"chapters": ["a", "b", "c"]})
        fe = ForEach(name="fe", items_path="chapters", body=inner_loop)

        result = fe.run(_ctx(state=state), {})

        # 每个 item 各自的内层 Loop 都被 Breaker 立即中断(跑一轮就结束),
        # 但 ForEach 本身没有被中断——三个 item 全部处理完。
        self.assertEqual(inner_runs, ["a", "b", "c"])
        self.assertEqual(result, {"iterations": 3, "items_path": "chapters"})
        self.assertNotIn("broken", result)


if __name__ == "__main__":
    unittest.main()
