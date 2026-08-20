import unittest

from bumaren_agent_workflow.engine.context import CheckpointRequest, LifecycleHooks, RunContext
from bumaren_agent_workflow.engine.primitives.checkpoint import Checkpoint
from bumaren_agent_workflow.state.backends.memory import InMemoryStateStore
from bumaren_agent_workflow.state.schema import SchemaError, StateSchema


def _ctx(**kwargs):
    return RunContext(state=InMemoryStateStore(), **kwargs)


class CheckpointNoHandlerTests(unittest.TestCase):
    def test_raises_runtime_error_naming_the_checkpoint(self):
        cp = Checkpoint(name="confirm_outline")
        with self.assertRaises(RuntimeError) as ctx_mgr:
            cp.run(_ctx(), {"draft": "x"})
        self.assertIn("confirm_outline", str(ctx_mgr.exception))


class CheckpointWithHandlerTests(unittest.TestCase):
    def test_handler_receives_request_and_result_merges_into_inputs(self):
        received = []

        def handler(request: CheckpointRequest):
            received.append(request)
            return {"approved": True}

        cp = Checkpoint(name="confirm_outline", prompt="Approve?")
        result = cp.run(_ctx(checkpoint_handler=handler), {"draft": "x"})

        self.assertEqual(result, {"draft": "x", "approved": True})
        self.assertEqual(received[0].name, "confirm_outline")
        self.assertEqual(received[0].prompt, "Approve?")
        self.assertEqual(received[0].context, {"draft": "x"})

    def test_resume_input_schema_validates_handler_output(self):
        def handler(request):
            return {"approved": "not a bool"}

        cp = Checkpoint(
            name="cp",
            resume_input_schema=StateSchema("resume", {"approved": bool}),
        )
        with self.assertRaises(SchemaError):
            cp.run(_ctx(checkpoint_handler=handler), {})

    def test_on_checkpoint_hook_fires(self):
        calls = []
        hooks = LifecycleHooks(on_checkpoint=lambda name: calls.append(name))
        cp = Checkpoint(name="cp", )
        ctx = _ctx(checkpoint_handler=lambda r: {}, hooks=hooks)
        cp.run(ctx, {})
        self.assertEqual(calls, ["cp"])


if __name__ == "__main__":
    unittest.main()
