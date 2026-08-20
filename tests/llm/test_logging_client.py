import json
import tempfile
import unittest
from pathlib import Path

from bumaren_agent_workflow.llm.client import ChatResponse, LLMClient, StreamEvent
from bumaren_agent_workflow.llm.logging_client import LoggingLLMClient
from bumaren_agent_workflow.llm.message import Message, ToolCall


class ScriptedLLMClient(LLMClient):
    def __init__(self, responses):
        self._responses = list(responses)

    def chat(self, messages, tools=None, response_schema=None, **params):
        return self._responses.pop(0)

    def stream(self, messages, tools=None, response_schema=None, **params):
        response = self._responses.pop(0)
        yield StreamEvent(delta="hi")
        yield StreamEvent(done=True, response=response)


def _final(content, tool_calls=None):
    return ChatResponse(
        message=Message(role="assistant", content=content, tool_calls=tool_calls or []),
        tool_calls=tool_calls or [],
        usage={"input_tokens": 1},
    )


class LoggingLLMClientTests(unittest.TestCase):
    def test_chat_writes_one_file_per_call_and_returns_response_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp) / "log"
            inner = ScriptedLLMClient([_final("first"), _final("second")])
            client = LoggingLLMClient(inner, log_dir)

            r1 = client.chat([Message(role="user", content="hi")])
            r2 = client.chat([Message(role="user", content="again")])

            self.assertEqual(r1.message.content, "first")
            self.assertEqual(r2.message.content, "second")

            files = sorted(log_dir.glob("*.json"))
            self.assertEqual(len(files), 2)

            payload = json.loads(files[0].read_text(encoding="utf-8"))
            self.assertEqual(payload["request"]["messages"][0]["content"], "hi")
            self.assertEqual(payload["response"]["message"]["content"], "first")
            self.assertEqual(payload["response"]["usage"], {"input_tokens": 1})

    def test_log_dir_is_created_if_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp) / "nested" / "log"
            client = LoggingLLMClient(ScriptedLLMClient([_final("ok")]), log_dir)
            client.chat([Message(role="user", content="hi")])
            self.assertTrue(log_dir.is_dir())
            self.assertEqual(len(list(log_dir.glob("*.json"))), 1)

    def test_records_tool_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp) / "log"
            tc = ToolCall(id="c1", name="lookup", arguments={"q": "x"})
            client = LoggingLLMClient(ScriptedLLMClient([_final(None, [tc])]), log_dir)
            client.chat([Message(role="user", content="hi")])

            payload = json.loads(next(log_dir.glob("*.json")).read_text(encoding="utf-8"))
            logged_tc = payload["response"]["message"]["tool_calls"][0]
            self.assertEqual(logged_tc, {"id": "c1", "name": "lookup", "arguments": {"q": "x"}})

    def test_stream_logs_only_on_done_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp) / "log"
            client = LoggingLLMClient(ScriptedLLMClient([_final("streamed")]), log_dir)

            events = list(client.stream([Message(role="user", content="hi")]))

            self.assertEqual(events[-1].response.message.content, "streamed")
            files = list(log_dir.glob("*.json"))
            self.assertEqual(len(files), 1)


if __name__ == "__main__":
    unittest.main()
