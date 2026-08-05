import unittest

from agent.toolset import ToolSet
from tools.schema import ToolSchema


def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


def greet(name: str) -> str:
    """Greet someone."""
    return f"hello {name}"


class ToolSetTests(unittest.TestCase):
    def test_from_funcs_generates_schemas(self):
        ts = ToolSet.from_funcs("math_tools", [add, greet])
        self.assertEqual(ts.name, "math_tools")
        self.assertEqual(len(ts.tools), 2)
        for func, schema in ts.tools:
            self.assertIsInstance(schema, ToolSchema)
            self.assertEqual(schema.name, func.__name__)

    def test_tool_names_returns_all_names(self):
        ts = ToolSet.from_funcs("math_tools", [add, greet])
        self.assertEqual(set(ts.tool_names()), {"add", "greet"})

    def test_empty_toolset_has_no_tools(self):
        ts = ToolSet(name="empty")
        self.assertEqual(ts.tools, [])
        self.assertEqual(ts.tool_names(), [])


if __name__ == "__main__":
    unittest.main()
