import unittest

from engine.context import RunContext
from engine.primitives.sequence import Sequence
from state.backends.memory import InMemoryStateStore


class _AddNode:
    def __init__(self, name, amount):
        self.name = name
        self.amount = amount

    def run(self, ctx, inputs):
        return {"value": inputs["value"] + self.amount}


class SequenceTests(unittest.TestCase):
    def setUp(self):
        self.ctx = RunContext(state=InMemoryStateStore())

    def test_empty_sequence_returns_inputs_unchanged(self):
        seq = Sequence(name="empty", nodes=[])
        result = seq.run(self.ctx, {"value": 1})
        self.assertEqual(result, {"value": 1})

    def test_chains_outputs_into_next_inputs(self):
        seq = Sequence(
            name="chain",
            nodes=[_AddNode("a", 1), _AddNode("b", 10), _AddNode("c", 100)],
        )
        result = seq.run(self.ctx, {"value": 0})
        self.assertEqual(result, {"value": 111})


if __name__ == "__main__":
    unittest.main()
