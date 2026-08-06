import unittest

from llm.message import ToolCall
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry
from tools.schema import schema_from_func


def add(a: int, b: int) -> int:
    return a + b


def boom() -> None:
    raise ValueError("kaboom")


class ToolExecutorTests(unittest.TestCase):
    def setUp(self):
        self.registry = ToolRegistry()
        self.registry.register("add", add, schema_from_func(add))
        self.registry.register("boom", boom, schema_from_func(boom))
        self.executor = ToolExecutor(self.registry)

    def test_execute_success(self):
        call = ToolCall(id="1", name="add", arguments={"a": 2, "b": 3})
        result = self.executor.execute(call)
        self.assertEqual(result.role, "tool")
        self.assertEqual(result.tool_call_id, "1")
        self.assertEqual(result.content, "5")

    def test_execute_function_raises_is_caught(self):
        call = ToolCall(id="2", name="boom", arguments={})
        result = self.executor.execute(call)
        self.assertEqual(result.role, "tool")
        self.assertEqual(result.content, "kaboom")

    def test_execute_unregistered_tool_does_not_crash(self):
        call = ToolCall(id="3", name="does_not_exist", arguments={})
        result = self.executor.execute(call)
        self.assertEqual(result.role, "tool")
        self.assertEqual(result.tool_call_id, "3")
        self.assertIn("未注册", result.content)

    def test_execute_all_runs_in_order(self):
        calls = [
            ToolCall(id="1", name="add", arguments={"a": 1, "b": 1}),
            ToolCall(id="2", name="does_not_exist", arguments={}),
            ToolCall(id="3", name="add", arguments={"a": 10, "b": 5}),
        ]
        results = self.executor.execute_all(calls)
        self.assertEqual([r.tool_call_id for r in results], ["1", "2", "3"])
        self.assertEqual(results[0].content, "2")
        self.assertEqual(results[2].content, "15")


if __name__ == "__main__":
    unittest.main()
