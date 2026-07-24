import unittest

from agent.memory import ConversationMemory
from llm.message import Message, ToolCall


def _msg(role, content=None, tool_calls=None, tool_call_id=None):
    return Message(role=role, content=content, tool_calls=tool_calls or [], tool_call_id=tool_call_id)


class RenderTests(unittest.TestCase):
    def test_render_prepends_system_prompt(self):
        mem = ConversationMemory(system_prompt="You are helpful.")
        mem.append(_msg("user", "hi"))
        rendered = mem.render()
        self.assertEqual(rendered[0].role, "system")
        self.assertEqual(rendered[0].content, "You are helpful.")
        self.assertEqual(rendered[1].content, "hi")

    def test_render_without_system_prompt(self):
        mem = ConversationMemory()
        mem.append(_msg("user", "hi"))
        rendered = mem.render()
        self.assertEqual(len(rendered), 1)
        self.assertEqual(rendered[0].role, "user")


class NeedsCompactionTests(unittest.TestCase):
    def test_false_when_no_max_tokens_set(self):
        mem = ConversationMemory()
        for _ in range(1000):
            mem.append(_msg("user", "x" * 1000))
        self.assertFalse(mem.needs_compaction())

    def test_true_once_estimated_tokens_exceed_max(self):
        mem = ConversationMemory(max_tokens=10)
        self.assertFalse(mem.needs_compaction())
        mem.append(_msg("user", "a" * 1000))
        self.assertTrue(mem.needs_compaction())


class CompactionBoundaryTests(unittest.TestCase):
    def test_keeps_last_n_messages_uncompacted(self):
        mem = ConversationMemory()
        for i in range(10):
            mem.append(_msg("user", str(i)))
        candidates = mem.compaction_candidates()
        # _KEEP_RECENT = 4, so the last 4 of 10 are kept out
        self.assertEqual(len(candidates), 6)
        self.assertEqual([m.content for m in candidates], [str(i) for i in range(6)])

    def test_boundary_never_splits_tool_call_from_its_result(self):
        mem = ConversationMemory()
        mem.append(_msg("user", "0"))
        mem.append(_msg("user", "1"))
        # assistant issues a tool call, followed immediately by its tool result;
        # these two must land on the same side of the split.
        mem.append(_msg("assistant", None, tool_calls=[ToolCall(id="c1", name="f", arguments={})]))
        mem.append(_msg("tool", "result", tool_call_id="c1"))
        mem.append(_msg("user", "2"))

        candidates = mem.compaction_candidates()
        # naive boundary (len - 4 = 1) would land inside the tool pair (index 2);
        # it must walk back to avoid splitting on a "tool" message.
        boundary = len(candidates)
        self.assertNotEqual(mem.messages[boundary - 1].role, "tool")

    def test_short_history_yields_no_candidates(self):
        mem = ConversationMemory()
        mem.append(_msg("user", "only one"))
        self.assertEqual(mem.compaction_candidates(), [])


class ApplyCompactionTests(unittest.TestCase):
    def test_replaces_candidates_with_summary_message(self):
        mem = ConversationMemory()
        for i in range(10):
            mem.append(_msg("user", str(i)))
        mem.apply_compaction("summary of 0-5")

        self.assertEqual(mem.messages[0].role, "system")
        self.assertEqual(mem.messages[0].content, "summary of 0-5")
        # the last _KEEP_RECENT=4 originals should remain
        self.assertEqual([m.content for m in mem.messages[1:]], ["6", "7", "8", "9"])

    def test_noop_when_nothing_to_compact(self):
        mem = ConversationMemory()
        mem.append(_msg("user", "only one"))
        mem.apply_compaction("summary")
        self.assertEqual(len(mem.messages), 1)
        self.assertEqual(mem.messages[0].content, "only one")


class EstimateTokensTests(unittest.TestCase):
    def test_empty_memory_is_zero(self):
        mem = ConversationMemory()
        self.assertEqual(mem._estimate_tokens(), 0)

    def test_counts_tool_call_text_too(self):
        mem = ConversationMemory()
        mem.append(
            _msg("assistant", None, tool_calls=[ToolCall(id="1", name="lookup", arguments={"q": "x"})])
        )
        self.assertGreater(mem._estimate_tokens(), 0)


if __name__ == "__main__":
    unittest.main()
