import unittest

from bumaren_agent_workflow.engine.context import RunContext
from bumaren_agent_workflow.engine.primitives.continuer import Continuer, LoopContinue
from bumaren_agent_workflow.state.backends.memory import InMemoryStateStore


def _ctx(**kwargs):
    kwargs.setdefault("state", InMemoryStateStore())
    return RunContext(**kwargs)


class ContinuerStandaloneTests(unittest.TestCase):
    def test_passthrough_when_predicate_is_false(self):
        continuer = Continuer(name="go", predicate=lambda ctx, inputs: False)
        result = continuer.run(_ctx(), {"x": 1})
        self.assertEqual(result, {"x": 1})

    def test_raises_loop_continue_with_current_outputs_when_predicate_is_true(self):
        continuer = Continuer(name="go", predicate=lambda ctx, inputs: inputs.get("pending"))
        with self.assertRaises(LoopContinue) as ctx_mgr:
            continuer.run(_ctx(), {"pending": True, "x": 1})
        self.assertEqual(ctx_mgr.exception.name, "go")
        self.assertEqual(ctx_mgr.exception.outputs, {"pending": True, "x": 1})

    def test_predicate_can_read_ctx_state_not_just_inputs(self):
        """predicate 拿到的是完整的 ctx,可以看 inputs 之外的状态,不局限于当前
        节点收到的 inputs——与 Breaker 的 predicate 是同一种能力(Callable 签名
        本身就允许任意代码),这里只是给 Continuer 单独留一份回归覆盖。"""
        ctx = _ctx()
        ctx.state.patch("pending_count", 2)
        continuer = Continuer(name="go", predicate=lambda ctx, inputs: ctx.state.get("pending_count", 0) > 0)

        with self.assertRaises(LoopContinue):
            continuer.run(ctx, {})


if __name__ == "__main__":
    unittest.main()
