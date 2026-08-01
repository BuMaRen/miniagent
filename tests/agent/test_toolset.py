import unittest

from agent.toolset import ToolSet, ToolSetRegistry
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


class ToolSetRegistryTests(unittest.TestCase):
    """按名检索工具集——stages.yaml 里 `tools: [research]` 就是走这张表。"""

    def setUp(self):
        self.registry = ToolSetRegistry()
        self.research = ToolSet.from_funcs("research_toolset", [add])

    def test_register_then_get_by_exact_name(self):
        self.assertTrue(self.registry.register(self.research))
        self.assertIs(self.registry.get("research_toolset"), self.research)

    def test_get_falls_back_to_the_toolset_suffix(self):
        # YAML 里逐个写 "_toolset" 只是噪音,省略也要能查到。
        self.registry.register(self.research)
        self.assertIs(self.registry.get("research"), self.research)

    def test_duplicate_register_returns_false_and_keeps_the_first(self):
        self.registry.register(self.research)
        other = ToolSet.from_funcs("research_toolset", [greet])
        self.assertFalse(self.registry.register(other))
        self.assertIs(self.registry.get("research"), self.research)

    def test_unknown_name_reports_the_registered_ones(self):
        self.registry.register(self.research)
        with self.assertRaises(KeyError) as caught:
            self.registry.get("nope")
        self.assertIn("research_toolset", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
