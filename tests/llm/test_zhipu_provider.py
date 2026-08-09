import unittest
from unittest.mock import MagicMock

try:
    from llm.providers.zhipu import (
        ZhipuClient,
        _append_schema_instruction,
        _build_response_format,
        _to_zhipu_message,
    )
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
    def test_returns_json_object_mode(self):
        # 智谱不支持把 schema 内嵌进 response_format,只有 json_object 这一种模式。
        self.assertEqual(_build_response_format(), {"type": "json_object"})


@unittest.skipIf(_IMPORT_ERROR is not None, f"zai-sdk package not installed: {_IMPORT_ERROR}")
class AppendSchemaInstructionTests(unittest.TestCase):
    def test_appends_system_message_with_schema_after_existing_messages(self):
        schema = {"type": "object", "properties": {"x": {"type": "integer"}}}
        messages = [{"role": "user", "content": "hi"}]
        result = _append_schema_instruction(messages, schema)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], {"role": "user", "content": "hi"})
        self.assertEqual(result[1]["role"], "system")
        self.assertIn('"integer"', result[1]["content"])

    def test_does_not_mutate_input_list(self):
        messages = [{"role": "user", "content": "hi"}]
        _append_schema_instruction(messages, {"type": "object"})
        self.assertEqual(messages, [{"role": "user", "content": "hi"}])


def _make_completion(content, completion_tokens=100):
    """构造一个满足 ZhipuClient.chat() 所需字段的假 completion 对象。"""
    message = MagicMock(content=content, tool_calls=[])
    choice = MagicMock(message=message)
    usage = MagicMock(completion_tokens=completion_tokens)
    usage.model_dump.return_value = {"completion_tokens": completion_tokens}
    return MagicMock(choices=[choice], usage=usage)


def _make_chunk(content_delta=None, usage_tokens=None):
    """构造一个满足 ZhipuClient.stream() 所需字段的假 stream chunk。"""
    delta = MagicMock(content=content_delta, tool_calls=[])
    choice = MagicMock(delta=delta)
    chunk = MagicMock(choices=[choice])
    if usage_tokens is not None:
        usage = MagicMock()
        usage.model_dump.return_value = {"completion_tokens": usage_tokens}
        chunk.usage = usage
    else:
        chunk.usage = None
    return chunk


@unittest.skipIf(_IMPORT_ERROR is not None, f"zai-sdk package not installed: {_IMPORT_ERROR}")
class ChatEmptyTurnRetryTests(unittest.TestCase):
    """GLM 思考模式偶发把整轮 token 花在推理上、content 与 tool_calls 都为空;
    这不是配置问题,重试同一份请求通常就能拿到正常回复,所以 chat() 要能自动重试
    ——而不是像早期一次错误的修复那样直接关掉思考模式(思考对小说创作是有用的)。
    """

    def _client(self):
        # max_tokens 特意选一个明显低于 STREAM_MAX_TOKENS_THRESHOLD 的值——这组
        # 测试要覆盖的是非流式 chat() 里的"空轮重试"逻辑,不能让它意外撞上
        # llm/client.py 的流式切换阈值(16384),那是另一套独立行为。
        client = ZhipuClient(api_key="x", model="glm-5.2", max_tokens=4096)
        client._client = MagicMock()
        return client

    def test_retries_until_non_empty_content(self):
        client = self._client()
        client._client.chat.completions.create.side_effect = [
            _make_completion(""),
            _make_completion(""),
            _make_completion('{"ok": 1}'),
        ]
        resp = client.chat([Message(role="user", content="hi")])
        self.assertEqual(resp.message.content, '{"ok": 1}')
        self.assertEqual(client._client.chat.completions.create.call_count, 3)

    def test_gives_up_after_max_retries_without_raising(self):
        client = self._client()
        client._client.chat.completions.create.side_effect = [
            _make_completion("") for _ in range(10)
        ]
        resp = client.chat([Message(role="user", content="hi")])
        self.assertIsNone(resp.message.content)
        # 首次 + 2 次重试 = 3 次
        self.assertEqual(client._client.chat.completions.create.call_count, 3)

    def test_does_not_retry_when_content_present_on_first_try(self):
        client = self._client()
        client._client.chat.completions.create.side_effect = [_make_completion("hi there")]
        resp = client.chat([Message(role="user", content="hi")])
        self.assertEqual(resp.message.content, "hi there")
        self.assertEqual(client._client.chat.completions.create.call_count, 1)


@unittest.skipIf(_IMPORT_ERROR is not None, f"zai-sdk package not installed: {_IMPORT_ERROR}")
class StreamEmptyTurnRetryTests(unittest.TestCase):
    def _client(self):
        client = ZhipuClient(api_key="x", model="glm-5.2")
        client._client = MagicMock()
        return client

    def test_retries_when_no_delta_was_ever_yielded(self):
        client = self._client()
        client._client.chat.completions.create.side_effect = [
            iter([_make_chunk(usage_tokens=50)]),  # 全程无 content、无 tool_calls
            iter([
                _make_chunk(content_delta="hello ", usage_tokens=10),
                _make_chunk(content_delta="world", usage_tokens=20),
            ]),
        ]
        events = list(client.stream([Message(role="user", content="hi")]))
        deltas = [e.delta for e in events if e.delta]
        done_events = [e for e in events if e.done]

        # 调用方只看到成功那一轮的增量,失败的第一轮完全透明。
        self.assertEqual(deltas, ["hello ", "world"])
        self.assertEqual(len(done_events), 1)
        self.assertEqual(done_events[0].response.message.content, "hello world")
        self.assertEqual(client._client.chat.completions.create.call_count, 2)


if __name__ == "__main__":
    unittest.main()
