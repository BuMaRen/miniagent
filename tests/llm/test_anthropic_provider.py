import unittest

try:
    from llm.providers.anthropic import _build_output_config, _extract_system, _to_anthropic_messages
    _IMPORT_ERROR = None
except ImportError as e:  # pragma: no cover - depends on optional dependency
    _IMPORT_ERROR = e

from llm.message import Message, ToolCall


@unittest.skipIf(_IMPORT_ERROR is not None, f"anthropic package not installed: {_IMPORT_ERROR}")
class ExtractSystemTests(unittest.TestCase):
    def test_no_system_messages_returns_none(self):
        self.assertIsNone(_extract_system([Message(role="user", content="hi")]))

    def test_joins_multiple_system_messages(self):
        messages = [
            Message(role="system", content="rule one"),
            Message(role="user", content="hi"),
            Message(role="system", content="rule two"),
        ]
        self.assertEqual(_extract_system(messages), "rule one\n\nrule two")


@unittest.skipIf(_IMPORT_ERROR is not None, f"anthropic package not installed: {_IMPORT_ERROR}")
class ToAnthropicMessagesTests(unittest.TestCase):
    def test_system_messages_are_dropped(self):
        messages = [Message(role="system", content="rule"), Message(role="user", content="hi")]
        result = _to_anthropic_messages(messages)
        self.assertEqual(result, [{"role": "user", "content": "hi"}])

    def test_tool_result_becomes_user_message_with_tool_result_block(self):
        messages = [Message(role="tool", content="42", tool_call_id="c1")]
        result = _to_anthropic_messages(messages)
        self.assertEqual(result, [
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "c1", "content": "42"}],
            }
        ])

    def test_consecutive_tool_results_merge_into_one_user_message(self):
        messages = [
            Message(role="tool", content="1", tool_call_id="c1"),
            Message(role="tool", content="2", tool_call_id="c2"),
        ]
        result = _to_anthropic_messages(messages)
        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0]["content"]), 2)

    def test_non_consecutive_tool_results_do_not_merge(self):
        messages = [
            Message(role="tool", content="1", tool_call_id="c1"),
            Message(role="user", content="in between"),
            Message(role="tool", content="2", tool_call_id="c2"),
        ]
        result = _to_anthropic_messages(messages)
        tool_result_groups = [m for m in result if m["role"] == "user" and isinstance(m["content"], list)]
        self.assertEqual(len(tool_result_groups), 2)

    def test_assistant_message_with_tool_calls_becomes_tool_use_blocks(self):
        msg = Message(
            role="assistant",
            content="thinking...",
            tool_calls=[ToolCall(id="c1", name="lookup", arguments={"q": "x"})],
        )
        result = _to_anthropic_messages([msg])
        self.assertEqual(len(result), 1)
        blocks = result[0]["content"]
        self.assertEqual(blocks[0], {"type": "text", "text": "thinking..."})
        self.assertEqual(blocks[1]["type"], "tool_use")
        self.assertEqual(blocks[1]["id"], "c1")
        self.assertEqual(blocks[1]["input"], {"q": "x"})

    def test_plain_assistant_message_without_tool_calls(self):
        result = _to_anthropic_messages([Message(role="assistant", content="hi")])
        self.assertEqual(result, [{"role": "assistant", "content": "hi"}])


@unittest.skipIf(_IMPORT_ERROR is not None, f"anthropic package not installed: {_IMPORT_ERROR}")
class BuildOutputConfigTests(unittest.TestCase):
    def test_wraps_schema_in_output_config_format(self):
        schema = {"type": "object", "properties": {"x": {"type": "integer"}}}
        result = _build_output_config(schema)
        self.assertEqual(
            result,
            {"format": {"type": "json_schema", "schema": schema}},
        )


if __name__ == "__main__":
    unittest.main()
