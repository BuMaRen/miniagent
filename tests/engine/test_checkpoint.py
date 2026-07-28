import unittest

from engine.context import CheckpointRequest, LifecycleHooks, ResumePoint, RunContext
from engine.primitives.checkpoint import Checkpoint, CheckpointPause
from state.backends.memory import InMemoryStateStore
from state.schema import SchemaError, StateSchema


def _ctx(**kwargs):
    return RunContext(state=InMemoryStateStore(), **kwargs)


class CheckpointNoHandlerTests(unittest.TestCase):
    def test_raises_checkpoint_pause_with_name(self):
        cp = Checkpoint(name="confirm_outline")
        with self.assertRaises(CheckpointPause) as ctx_mgr:
            cp.run(_ctx(), {"draft": "x"})
        self.assertEqual(ctx_mgr.exception.checkpoint_name, "confirm_outline")
        # node_index/inputs are filled in later by Workflow, not by Checkpoint itself
        self.assertIsNone(ctx_mgr.exception.node_index)


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


class CheckpointResumeTests(unittest.TestCase):
    def test_resume_matching_name_consumes_resume_point(self):
        resume = ResumePoint(
            checkpoint_name="cp", node_index=2, resume_input={"approved": True}
        )
        ctx = _ctx(resume=resume)
        cp = Checkpoint(name="cp")

        result = cp.run(ctx, {"draft": "x"})
        self.assertEqual(result, {"draft": "x", "approved": True})
        self.assertIsNone(ctx.resume)

    def test_resume_for_different_checkpoint_name_falls_through(self):
        resume = ResumePoint(
            checkpoint_name="other_cp", node_index=0, resume_input={"approved": True}
        )
        ctx = _ctx(resume=resume)
        cp = Checkpoint(name="cp")

        with self.assertRaises(CheckpointPause):
            cp.run(ctx, {})
        # unrelated resume point should be left untouched
        self.assertIsNotNone(ctx.resume)

    def test_resume_input_validated_against_schema(self):
        resume = ResumePoint(
            checkpoint_name="cp", node_index=0, resume_input={"approved": "nope"}
        )
        ctx = _ctx(resume=resume)
        cp = Checkpoint(
            name="cp", resume_input_schema=StateSchema("resume", {"approved": bool})
        )
        with self.assertRaises(SchemaError):
            cp.run(ctx, {})


if __name__ == "__main__":
    unittest.main()
