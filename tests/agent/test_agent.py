import json
import unittest

from agent.agent import Agent
from agent.memory import ConversationMemory
from agent.toolset import ToolSet
from llm.client import ChatResponse, LLMClient
from llm.message import Message, ToolCall
from state.schema import StateSchema
from tools.registry import ToolRegistry


class ScriptedLLMClient(LLMClient):
    """Returns pre-scripted ChatResponses in order; records every call it received."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def chat(self, messages, tools=None, **params):
        self.calls.append({"messages": list(messages), "tools": tools, "params": params})
        if not self._responses:
            raise AssertionError("ScriptedLLMClient ran out of scripted responses")
        return self._responses.pop(0)


def _final(content):
    return ChatResponse(message=Message(role="assistant", content=content), tool_calls=[])


def _tool_call_response(call_id, name, arguments):
    tc = ToolCall(id=call_id, name=name, arguments=arguments)
    return ChatResponse(
        message=Message(role="assistant", content=None, tool_calls=[tc]), tool_calls=[tc]
    )


def double(x: int) -> int:
    return x * 2


class AgentOutputParsingTests(unittest.TestCase):
    def test_run_returns_parsed_json_dict(self):
        client = ScriptedLLMClient([_final('{"result": "ok"}')])
        agent = Agent(client=client, memory=ConversationMemory(), registry=ToolRegistry())
        outputs = agent.run(ctx=None, inputs={"task": "do x"})
        self.assertEqual(outputs, {"result": "ok"})

    def test_run_wraps_plain_text_output(self):
        client = ScriptedLLMClient([_final("just some prose")])
        agent = Agent(client=client, memory=ConversationMemory(), registry=ToolRegistry())
        outputs = agent.run(ctx=None, inputs={})
        self.assertEqual(outputs, {"output": "just some prose"})

    def test_run_wraps_json_array_as_output_not_dict(self):
        client = ScriptedLLMClient([_final("[1, 2, 3]")])
        agent = Agent(client=client, memory=ConversationMemory(), registry=ToolRegistry())
        outputs = agent.run(ctx=None, inputs={})
        # a JSON array isn't a dict, so it falls back to the {"output": ...} wrapper
        self.assertEqual(outputs, {"output": "[1, 2, 3]"})


class AgentOutputSchemaTests(unittest.TestCase):
    def test_response_schema_is_none_when_output_schema_unset(self):
        client = ScriptedLLMClient([_final('{"result": "ok"}')])
        agent = Agent(client=client, memory=ConversationMemory(), registry=ToolRegistry())
        agent.run(ctx=None, inputs={})
        self.assertIsNone(client.calls[0]["params"]["response_schema"])

    def test_response_schema_is_converted_from_output_schema(self):
        client = ScriptedLLMClient([_final('{"answer": 42}')])
        output_schema = StateSchema("out", {"answer": int})
        agent = Agent(
            client=client,
            memory=ConversationMemory(),
            registry=ToolRegistry(),
            output_schema=output_schema,
        )
        agent.run(ctx=None, inputs={})
        self.assertEqual(
            client.calls[0]["params"]["response_schema"], output_schema.to_json_schema()
        )

    def test_response_schema_still_passed_alongside_tools_during_tool_loop(self):
        output_schema = StateSchema("out", {"answer": int})
        client = ScriptedLLMClient(
            [_tool_call_response("c1", "double", {"x": 21}), _final('{"answer": 42}')]
        )
        agent = Agent(
            client=client,
            memory=ConversationMemory(),
            registry=ToolRegistry(),
            output_schema=output_schema,
        )
        agent.load_toolset(ToolSet.from_funcs("math", [double]))

        agent.run(ctx=None, inputs={})

        for call in client.calls:
            self.assertIsNotNone(call["tools"])
            self.assertEqual(call["params"]["response_schema"], output_schema.to_json_schema())


class AgentToolLoopTests(unittest.TestCase):
    def test_tool_call_executed_and_result_fed_back(self):
        registry = ToolRegistry()
        agent = Agent(
            client=ScriptedLLMClient(
                [_tool_call_response("c1", "double", {"x": 21}), _final('{"answer": 42}')]
            ),
            memory=ConversationMemory(),
            registry=registry,
        )
        agent.load_toolset(ToolSet.from_funcs("math", [double]))

        outputs = agent.run(ctx=None, inputs={"task": "double 21"})

        self.assertEqual(outputs, {"answer": 42})
        tool_messages = [m for m in agent.memory.messages if m.role == "tool"]
        self.assertEqual(len(tool_messages), 1)
        self.assertEqual(tool_messages[0].content, "42")
        self.assertEqual(tool_messages[0].tool_call_id, "c1")

    def test_max_steps_bounds_the_loop(self):
        # every response requests a tool call, so the loop would run forever
        # without max_steps enforcing a hard stop.
        responses = [_tool_call_response(f"c{i}", "double", {"x": i}) for i in range(10)]
        client = ScriptedLLMClient(responses)
        registry = ToolRegistry()
        agent = Agent(
            client=client, memory=ConversationMemory(), registry=registry, max_steps=3
        )
        agent.load_toolset(ToolSet.from_funcs("math", [double]))

        agent.run(ctx=None, inputs={})

        self.assertEqual(len(client.calls), 3)


class AgentLoadToolsetTests(unittest.TestCase):
    def test_append_mode_keeps_previous_toolsets(self):
        agent = Agent(
            client=ScriptedLLMClient([_final("{}")]),
            memory=ConversationMemory(),
            registry=ToolRegistry(),
        )
        agent.load_toolset(ToolSet.from_funcs("math", [double]))

        def greet(name: str) -> str:
            return f"hi {name}"

        agent.load_toolset(ToolSet.from_funcs("greeting", [greet]))

        names = {s.name for s in agent.registry.schemas()}
        self.assertEqual(names, {"double", "greet"})
        self.assertEqual(len(agent.toolsets), 2)

    def test_replace_mode_unregisters_previous_toolsets(self):
        agent = Agent(
            client=ScriptedLLMClient([_final("{}")]),
            memory=ConversationMemory(),
            registry=ToolRegistry(),
        )
        agent.load_toolset(ToolSet.from_funcs("math", [double]))

        def greet(name: str) -> str:
            return f"hi {name}"

        agent.load_toolset(ToolSet.from_funcs("greeting", [greet]), mode="replace")

        names = {s.name for s in agent.registry.schemas()}
        self.assertEqual(names, {"greet"})
        self.assertEqual(len(agent.toolsets), 1)

    def test_duplicate_tool_name_raises(self):
        agent = Agent(
            client=ScriptedLLMClient([_final("{}")]),
            memory=ConversationMemory(),
            registry=ToolRegistry(),
        )
        agent.load_toolset(ToolSet.from_funcs("math", [double]))
        with self.assertRaises(ValueError):
            agent.load_toolset(ToolSet.from_funcs("math_again", [double]))

    def test_unknown_mode_raises(self):
        agent = Agent(
            client=ScriptedLLMClient([_final("{}")]),
            memory=ConversationMemory(),
            registry=ToolRegistry(),
        )
        with self.assertRaises(ValueError):
            agent.load_toolset(ToolSet.from_funcs("math", [double]), mode="bogus")

    def test_custom_registry_and_executor_stay_in_sync(self):
        # regression guard for the __post_init__ pitfall documented on Agent:
        # a custom registry without an explicit executor must not silently
        # fall back to operating on the global default_registry.
        registry = ToolRegistry()
        agent = Agent(
            client=ScriptedLLMClient(
                [_tool_call_response("c1", "double", {"x": 5}), _final('{"ok": true}')]
            ),
            memory=ConversationMemory(),
            registry=registry,
        )
        agent.load_toolset(ToolSet.from_funcs("math", [double]))
        outputs = agent.run(ctx=None, inputs={})
        self.assertEqual(outputs, {"ok": True})


class AgentCompactionTests(unittest.TestCase):
    def test_compact_summarizes_and_replaces_old_messages(self):
        client = ScriptedLLMClient([_final("a short summary")])
        memory = ConversationMemory()
        for i in range(10):
            memory.append(Message(role="user", content=str(i)))
        agent = Agent(client=client, memory=memory, registry=ToolRegistry())

        agent._compact()

        self.assertEqual(len(client.calls), 1)
        self.assertEqual(memory.messages[0].role, "system")
        self.assertEqual(memory.messages[0].content, "a short summary")
        self.assertEqual([m.content for m in memory.messages[1:]], ["6", "7", "8", "9"])

    def test_compact_is_noop_when_nothing_to_summarize(self):
        client = ScriptedLLMClient([])
        memory = ConversationMemory()
        memory.append(Message(role="user", content="only one"))
        agent = Agent(client=client, memory=memory, registry=ToolRegistry())

        agent._compact()  # must not call client.chat when there are no candidates

        self.assertEqual(len(client.calls), 0)
        self.assertEqual(len(memory.messages), 1)

    def test_run_triggers_compaction_when_memory_grows_past_max_tokens(self):
        registry = ToolRegistry()
        responses = [
            _tool_call_response("c1", "double", {"x": 1}),
            _tool_call_response("c2", "double", {"x": 2}),
            _final("compacted-summary"),  # consumed by the compaction call
            _final('{"done": true}'),
        ]
        client = ScriptedLLMClient(responses)
        memory = ConversationMemory(max_tokens=1)  # always "needs" compaction once non-trivial
        agent = Agent(client=client, memory=memory, registry=registry, max_steps=10)
        agent.load_toolset(ToolSet.from_funcs("math", [double]))

        outputs = agent.run(ctx=None, inputs={"task": "go"})

        self.assertEqual(outputs, {"done": True})
        # somewhere in memory there should be a system message holding the
        # compaction summary, proving _compact actually ran mid-loop.
        summaries = [m.content for m in memory.messages if m.role == "system"]
        self.assertIn("compacted-summary", summaries)


if __name__ == "__main__":
    unittest.main()
