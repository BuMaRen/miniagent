import unittest

from engine.context import LifecycleHooks, RunContext
from engine.stage import ExecutorRegistry, Stage, default_registry, executor
from state.backends.memory import InMemoryStateStore
from state.schema import SchemaError, StateSchema


def _dummy_executor(ctx, inputs):
    return inputs


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


class ExecutorRegistryTests(unittest.TestCase):
    def setUp(self):
        self.registry = ExecutorRegistry()

    def test_register_returns_true_on_success(self):
        self.assertTrue(self.registry.register("_dummy_executor", _dummy_executor))
        self.assertIs(self.registry.get("_dummy_executor"), _dummy_executor)

    def test_register_duplicate_returns_false(self):
        self.registry.register("_dummy_executor", _dummy_executor)
        self.assertFalse(self.registry.register("_dummy_executor", _dummy_executor))

    def test_get_missing_raises_keyerror(self):
        with self.assertRaises(KeyError):
            self.registry.get("nope")

    def test_unregister_removes_executor(self):
        self.registry.register("_dummy_executor", _dummy_executor)
        self.registry.unregister("_dummy_executor")
        with self.assertRaises(KeyError):
            self.registry.get("_dummy_executor")

    def test_unregister_missing_is_noop(self):
        self.registry.unregister("never_registered")  # should not raise


class ExecutorDecoratorTests(unittest.TestCase):
    def tearDown(self):
        default_registry.unregister("_decorated_dummy")

    def test_executor_decorator_registers_to_default_registry(self):
        @executor
        def _decorated_dummy(ctx, inputs):
            return inputs

        self.assertIs(default_registry.get("_decorated_dummy"), _decorated_dummy)


if __name__ == "__main__":
    unittest.main()
