import unittest

from bumaren_agent_workflow.llm.client import ChatResponse
from bumaren_agent_workflow.llm.message import Message, ToolCall


class MessageTests(unittest.TestCase):
    def test_defaults(self):
        m = Message(role="user")
        self.assertIsNone(m.content)
        self.assertEqual(m.tool_calls, [])
        self.assertIsNone(m.tool_call_id)

    def test_tool_calls_default_is_independent_per_instance(self):
        a = Message(role="assistant")
        b = Message(role="assistant")
        a.tool_calls.append(ToolCall(id="1", name="f", arguments={}))
        self.assertEqual(b.tool_calls, [])


class ChatResponseTests(unittest.TestCase):
    def test_defaults(self):
        resp = ChatResponse(message=Message(role="assistant", content="hi"))
        self.assertEqual(resp.tool_calls, [])
        self.assertEqual(resp.usage, {})


if __name__ == "__main__":
    unittest.main()
