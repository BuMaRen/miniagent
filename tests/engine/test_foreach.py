import unittest

from engine.context import LifecycleHooks, RunContext
from engine.primitives.foreach import ForEach
from state.backends.memory import InMemoryStateStore


class _RecordingBody:
    def __init__(self, name, item_path, state):
        self.name = name
        self.item_path = item_path
        self.state = state
        self.seen_items = []

    def run(self, ctx, inputs):
        self.seen_items.append(ctx.state.get(self.item_path))
        return {}


class ForEachTests(unittest.TestCase):
    def setUp(self):
        self.state = InMemoryStateStore(initial={"chapters": ["one", "two", "three"]})
        self.ctx = RunContext(state=self.state)

    def test_body_runs_once_per_item_in_order(self):
        body = _RecordingBody("body", "_foreach.fe.item", self.state)
        fe = ForEach(name="fe", items_path="chapters", body=body)
        result = fe.run(self.ctx, {})
        self.assertEqual(body.seen_items, ["one", "two", "three"])
        self.assertEqual(result, {"iterations": 3, "items_path": "chapters"})

    def test_index_advances_in_state(self):
        body = _RecordingBody("body", "_foreach.fe.item", self.state)
        fe = ForEach(name="fe", items_path="chapters", body=body)
        fe.run(self.ctx, {})
        self.assertEqual(self.state.get("_foreach.fe.index"), 3)

    def test_item_path_cleared_after_completion(self):
        body = _RecordingBody("body", "_foreach.fe.item", self.state)
        fe = ForEach(name="fe", items_path="chapters", body=body)
        fe.run(self.ctx, {})
        self.assertIsNone(self.state.get("_foreach.fe.item"))

    def test_custom_index_and_item_paths(self):
        body = _RecordingBody("body", "cursor.item", self.state)
        fe = ForEach(
            name="fe",
            items_path="chapters",
            body=body,
            index_path="cursor.index",
            item_path="cursor.item",
        )
        fe.run(self.ctx, {})
        self.assertEqual(body.seen_items, ["one", "two", "three"])
        self.assertEqual(self.state.get("cursor.index"), 3)

    def test_resumes_from_existing_index(self):
        self.state.patch("_foreach.fe.index", 1)
        body = _RecordingBody("body", "_foreach.fe.item", self.state)
        fe = ForEach(name="fe", items_path="chapters", body=body)
        fe.run(self.ctx, {})
        self.assertEqual(body.seen_items, ["two", "three"])

    def test_empty_items_runs_zero_iterations(self):
        state = InMemoryStateStore(initial={"chapters": []})
        ctx = RunContext(state=state)
        body = _RecordingBody("body", "_foreach.fe.item", state)
        fe = ForEach(name="fe", items_path="chapters", body=body)
        result = fe.run(ctx, {})
        self.assertEqual(result["iterations"], 0)
        self.assertEqual(body.seen_items, [])

    def test_missing_items_path_defaults_to_empty(self):
        state = InMemoryStateStore()
        ctx = RunContext(state=state)
        body = _RecordingBody("body", "_foreach.fe.item", state)
        fe = ForEach(name="fe", items_path="chapters", body=body)
        result = fe.run(ctx, {})
        self.assertEqual(result["iterations"], 0)

    def test_hooks_fire_per_iteration(self):
        calls = []
        hooks = LifecycleHooks(
            before_loop_iteration=lambda name, i: calls.append(("before", name, i)),
            after_loop_iteration=lambda name, i, ok: calls.append(("after", name, i, ok)),
        )
        ctx = RunContext(state=self.state, hooks=hooks)
        body = _RecordingBody("body", "_foreach.fe.item", self.state)
        fe = ForEach(name="fe", items_path="chapters", body=body)
        fe.run(ctx, {})
        self.assertEqual(calls[0], ("before", "fe", 0))
        self.assertEqual(calls[-1], ("after", "fe", 2, True))

    def test_body_does_not_leak_mutations_across_rounds(self):
        seen_inputs = []

        class _MutatingNode:
            name = "n"

            def run(self, ctx, inputs):
                seen_inputs.append(dict(inputs))
                inputs["mutated"] = True  # would leak to next round if not copied
                return {}

        fe = ForEach(name="fe", items_path="chapters", body=_MutatingNode())
        fe.run(self.ctx, {"mutated": False})
        # if inputs were shared across rounds, later rounds would see mutated=True
        self.assertTrue(all(round_inputs["mutated"] is False for round_inputs in seen_inputs))


if __name__ == "__main__":
    unittest.main()
