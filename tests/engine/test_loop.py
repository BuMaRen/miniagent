import unittest

from engine.context import CheckpointRequest, LifecycleHooks, RunContext
from engine.primitives.loop import Loop, LoopExceededError, OnExceed
from state.backends.memory import InMemoryStateStore


class _FixedNode:
    """Returns a fixed dict regardless of inputs."""

    def __init__(self, name, output):
        self.name = name
        self.output = output

    def run(self, ctx, inputs):
        return dict(self.output)


class _ScriptedCritic:
    """Returns a scripted sequence of verdicts, one per call; repeats the last."""

    def __init__(self, name, verdicts):
        self.name = name
        self._verdicts = list(verdicts)
        self.calls = []

    def run(self, ctx, inputs):
        self.calls.append(dict(inputs))
        verdict = self._verdicts.pop(0) if len(self._verdicts) > 1 else self._verdicts[0]
        return dict(verdict)


class _EchoReviser:
    """Bumps a counter each time it's invoked, to prove it ran."""

    def __init__(self, name):
        self.name = name
        self.calls = 0

    def run(self, ctx, inputs):
        self.calls += 1
        return {"draft": inputs.get("draft", "") + "!", "revisions": self.calls}


def _make_ctx(**kwargs):
    return RunContext(state=InMemoryStateStore(), **kwargs)


class LoopPassesImmediatelyTests(unittest.TestCase):
    def test_producer_output_returned_when_critic_passes_first_try(self):
        producer = _FixedNode("producer", {"draft": "v1"})
        critic = _ScriptedCritic("critic", [{"passed": True, "feedback": ""}])
        reviser = _EchoReviser("reviser")
        loop = Loop(name="loop", producer=producer, critic=critic, reviser=reviser)

        result = loop.run(_make_ctx(), {})
        self.assertEqual(result, {"draft": "v1"})
        self.assertEqual(reviser.calls, 0)


class LoopEventuallyPassesTests(unittest.TestCase):
    def test_reviser_runs_until_critic_passes(self):
        producer = _FixedNode("producer", {"draft": "v1"})
        critic = _ScriptedCritic(
            "critic",
            [
                {"passed": False, "feedback": "needs work"},
                {"passed": False, "feedback": "still needs work"},
                {"passed": True, "feedback": ""},
            ],
        )
        reviser = _EchoReviser("reviser")
        loop = Loop(
            name="loop", producer=producer, critic=critic, reviser=reviser, max_iterations=5
        )

        result = loop.run(_make_ctx(), {})
        self.assertEqual(reviser.calls, 2)
        self.assertEqual(result["draft"], "v1!!")

    def test_hooks_fire_per_iteration(self):
        calls = []
        hooks = LifecycleHooks(
            before_loop_iteration=lambda name, i: calls.append(("before", name, i)),
            after_loop_iteration=lambda name, i, passed: calls.append(("after", name, i, passed)),
        )
        producer = _FixedNode("producer", {"draft": "v1"})
        critic = _ScriptedCritic(
            "critic",
            [
                {"passed": False, "feedback": "x"},
                {"passed": True, "feedback": ""},
            ],
        )
        reviser = _EchoReviser("reviser")
        loop = Loop(name="loop", producer=producer, critic=critic, reviser=reviser)

        loop.run(_make_ctx(hooks=hooks), {})
        self.assertEqual(calls[0], ("before", "loop", 0))
        self.assertEqual(calls[1], ("after", "loop", 0, True))


class LoopExceedTests(unittest.TestCase):
    def _never_passing_loop(self, on_exceed, max_iterations=2):
        producer = _FixedNode("producer", {"draft": "v1"})
        critic = _ScriptedCritic("critic", [{"passed": False, "feedback": "nope"}])
        reviser = _EchoReviser("reviser")
        return Loop(
            name="loop",
            producer=producer,
            critic=critic,
            reviser=reviser,
            max_iterations=max_iterations,
            on_exceed=on_exceed,
        )

    def test_accept_last_returns_last_version(self):
        loop = self._never_passing_loop(OnExceed.ACCEPT_LAST, max_iterations=3)
        result = loop.run(_make_ctx(), {})
        self.assertEqual(result["draft"], "v1!!!")

    def test_raise_raises_loop_exceeded_error(self):
        loop = self._never_passing_loop(OnExceed.RAISE)
        with self.assertRaises(LoopExceededError):
            loop.run(_make_ctx(), {})

    def test_escalate_without_handler_raises_runtime_error(self):
        loop = self._never_passing_loop(OnExceed.ESCALATE_TO_CHECKPOINT)
        with self.assertRaises(RuntimeError):
            loop.run(_make_ctx(), {})

    def test_escalate_with_handler_delegates_to_human(self):
        received: list[CheckpointRequest] = []

        def handler(request: CheckpointRequest):
            received.append(request)
            return {"draft": "human-approved"}

        loop = self._never_passing_loop(OnExceed.ESCALATE_TO_CHECKPOINT, max_iterations=2)
        ctx = _make_ctx(checkpoint_handler=handler)
        result = loop.run(ctx, {})

        self.assertEqual(result, {"draft": "human-approved"})
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].name, "loop")
        self.assertIn("draft", received[0].context)

    def test_unknown_on_exceed_raises_value_error(self):
        loop = self._never_passing_loop(OnExceed.ACCEPT_LAST)
        loop.on_exceed = "bogus"  # bypass enum typing to hit the else branch
        with self.assertRaises(ValueError):
            loop.run(_make_ctx(), {})


if __name__ == "__main__":
    unittest.main()
