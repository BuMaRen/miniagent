import unittest

from bumaren_agent_workflow.engine.context import LifecycleHooks, RunContext
from bumaren_agent_workflow.engine.stage import Stage
from bumaren_agent_workflow.state.backends.memory import InMemoryStateStore
from bumaren_agent_workflow.state.schema import SchemaError, StateSchema


class StageRunTests(unittest.TestCase):
    def setUp(self):
        self.state = InMemoryStateStore(initial={"story": {"title": "Draft"}})
        self.ctx = RunContext(state=self.state)

    def test_basic_executor_roundtrip(self):
        def executor(ctx, inputs):
            return {"result": inputs["x"] * 2}

        stage = Stage(name="double", executor=executor)
        outputs = stage.run(self.ctx, {"x": 5})
        self.assertEqual(outputs, {"result": 10})

    def test_input_schema_validation_rejects_bad_input(self):
        stage = Stage(
            name="s",
            executor=lambda ctx, inputs: inputs,
            input_schema=StateSchema("in", {"x": int}),
        )
        with self.assertRaises(SchemaError):
            stage.run(self.ctx, {"x": "not an int"})

    def test_output_schema_validation_rejects_bad_output(self):
        stage = Stage(
            name="s",
            executor=lambda ctx, inputs: {"y": "not an int"},
            output_schema=StateSchema("out", {"y": int}),
        )
        with self.assertRaises(SchemaError):
            stage.run(self.ctx, {})

    def test_reads_injects_state_slice_into_inputs(self):
        seen = {}

        def executor(ctx, inputs):
            seen.update(inputs)
            return {}

        stage = Stage(name="s", executor=executor, reads=["story.title"])
        stage.run(self.ctx, {"foo": "bar"})
        self.assertEqual(seen["state"], {"story.title": "Draft"})
        self.assertEqual(seen["foo"], "bar")

    def test_writes_patches_outputs_back_to_state(self):
        stage = Stage(
            name="s",
            executor=lambda ctx, inputs: {"story.title": "Final"},
            writes=["story.title"],
        )
        stage.run(self.ctx, {})
        self.assertEqual(self.state.get("story.title"), "Final")

    def test_before_and_after_stage_hooks_fire(self):
        calls = []
        hooks = LifecycleHooks(
            before_stage=lambda name, inputs: calls.append(("before", name, dict(inputs))),
            after_stage=lambda name, outputs: calls.append(("after", name, dict(outputs))),
        )
        ctx = RunContext(state=self.state, hooks=hooks)
        stage = Stage(name="hooked", executor=lambda ctx, inputs: {"ok": True})
        stage.run(ctx, {"in": 1})
        self.assertEqual(calls[0], ("before", "hooked", {"in": 1}))
        self.assertEqual(calls[1], ("after", "hooked", {"ok": True}))

    def test_no_reads_or_writes_skips_state_interaction(self):
        stage = Stage(name="s", executor=lambda ctx, inputs: {"echo": inputs})
        before = self.state.snapshot()
        outputs = stage.run(self.ctx, {"a": 1})
        self.assertEqual(self.state.snapshot(), before)
        self.assertEqual(outputs, {"echo": {"a": 1}})


if __name__ == "__main__":
    unittest.main()
