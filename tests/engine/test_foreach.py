import unittest

from engine.context import LifecycleHooks, RunContext
from engine.primitives.checkpoint import CheckpointPause
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

    def test_checkpoint_pause_from_body_advances_index_before_bubbling(self):
        # 回归测试:body 内部放了一个"每轮结束后暂停"的 Checkpoint(比如场景方
        # 想让人工在每个 item 处理完之后决定是否继续)。之前的实现里,advance
        # 只在 body.run() 正常返回后执行——CheckpointPause 从 body 内部抛出时会
        # 跳过 advance,导致恢复后把刚处理完的这一项重新跑一遍(novel 场景里
        # 表现为:每次在 chapter_pause 处暂停后,续跑又从同一章开始)。
        class _PausingBody:
            name = "body"

            def __init__(self, item_path, state):
                self.item_path = item_path
                self.state = state
                self.seen_items = []

            def run(self, ctx, inputs):
                self.seen_items.append(ctx.state.get(self.item_path))
                raise CheckpointPause("per_item_pause")

        body = _PausingBody("_foreach.fe.item", self.state)
        fe = ForEach(name="fe", items_path="chapters", body=body)

        with self.assertRaises(CheckpointPause):
            fe.run(self.ctx, {})
        self.assertEqual(body.seen_items, ["one"])
        self.assertEqual(self.state.get("_foreach.fe.index"), 1)

        # 续跑:应该处理下一项("two"),而不是重新处理 "one"。
        with self.assertRaises(CheckpointPause):
            fe.run(self.ctx, {})
        self.assertEqual(body.seen_items, ["one", "two"])
        self.assertEqual(self.state.get("_foreach.fe.index"), 2)

    def test_other_exceptions_from_body_do_not_advance_index(self):
        class _FailingBody:
            name = "body"

            def run(self, ctx, inputs):
                raise RuntimeError("boom")

        fe = ForEach(name="fe", items_path="chapters", body=_FailingBody())
        with self.assertRaises(RuntimeError):
            fe.run(self.ctx, {})
        self.assertEqual(self.state.get("_foreach.fe.index"), 0)

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
