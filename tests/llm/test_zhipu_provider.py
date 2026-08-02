import unittest

try:
    from llm.providers.zhipu import _build_response_format, _to_zhipu_message
    _IMPORT_ERROR = None
except ImportError as e:  # pragma: no cover - depends on optional dependency
    _IMPORT_ERROR = e

from llm.message import Message, ToolCall


@unittest.skipIf(_IMPORT_ERROR is not None, f"zai-sdk package not installed: {_IMPORT_ERROR}")
class ToZhipuMessageTests(unittest.TestCase):
    def test_plain_message(self):
        result = _to_zhipu_message(Message(role="user", content="hi"))
        self.assertEqual(result, {"role": "user", "content": "hi"})

    def test_tool_result_message_uses_tool_call_id(self):
        msg = Message(role="tool", content="42", tool_call_id="c1")
        result = _to_zhipu_message(msg)
        self.assertEqual(result, {"role": "tool", "content": "42", "tool_call_id": "c1"})

    def test_tool_result_message_with_no_content_defaults_to_empty_string(self):
        msg = Message(role="tool", content=None, tool_call_id="c1")
        result = _to_zhipu_message(msg)
        self.assertEqual(result["content"], "")

    def test_assistant_message_with_tool_calls(self):
        msg = Message(
            role="assistant",
            content=None,
            tool_calls=[ToolCall(id="c1", name="lookup", arguments={"q": "x"})],
        )
        result = _to_zhipu_message(msg)
        self.assertEqual(result["role"], "assistant")
        self.assertEqual(len(result["tool_calls"]), 1)
        self.assertEqual(result["tool_calls"][0]["id"], "c1")
        self.assertEqual(result["tool_calls"][0]["function"]["name"], "lookup")
        self.assertEqual(result["tool_calls"][0]["function"]["arguments"], '{"q": "x"}')


@unittest.skipIf(_IMPORT_ERROR is not None, f"zai-sdk package not installed: {_IMPORT_ERROR}")
class BuildResponseFormatTests(unittest.TestCase):
    def test_wraps_schema_in_strict_json_schema_response_format(self):
        schema = {"type": "object", "properties": {"x": {"type": "integer"}}}
        result = _build_response_format(schema)
        self.assertEqual(
            result,
            {"type": "json_schema", "json_schema": {"name": "output", "schema": schema, "strict": True}},
        )


if __name__ == "__main__":
    unittest.main()
