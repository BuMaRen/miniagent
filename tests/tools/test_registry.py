import unittest

from tools.registry import ToolRegistry, default_registry, tool
from tools.schema import ToolSchema, schema_from_func


def _dummy(x: int) -> int:
    return x


class ToolRegistryTests(unittest.TestCase):
    def setUp(self):
        self.registry = ToolRegistry()
        self.schema = schema_from_func(_dummy)

    def test_register_returns_true_on_success(self):
        self.assertTrue(self.registry.register("_dummy", _dummy, self.schema))
        self.assertIs(self.registry.get("_dummy"), _dummy)

    def test_register_duplicate_returns_false(self):
        self.registry.register("_dummy", _dummy, self.schema)
        self.assertFalse(self.registry.register("_dummy", _dummy, self.schema))

    def test_register_name_mismatch_raises(self):
        with self.assertRaises(ValueError):
            self.registry.register("wrong_name", _dummy, self.schema)

    def test_get_missing_raises_keyerror(self):
        with self.assertRaises(KeyError):
            self.registry.get("nope")

    def test_unregister_removes_tool(self):
        self.registry.register("_dummy", _dummy, self.schema)
        self.registry.unregister("_dummy")
        with self.assertRaises(KeyError):
            self.registry.get("_dummy")

    def test_unregister_missing_is_noop(self):
        self.registry.unregister("never_registered")  # should not raise

    def test_schemas_returns_all_registered(self):
        self.registry.register("_dummy", _dummy, self.schema)
        schemas = self.registry.schemas()
        self.assertEqual(len(schemas), 1)
        self.assertIsInstance(schemas[0], ToolSchema)
        self.assertEqual(schemas[0].name, "_dummy")


class ToolDecoratorTests(unittest.TestCase):
    def tearDown(self):
        default_registry.unregister("_decorated_dummy")

    def test_tool_decorator_registers_to_default_registry(self):
        @tool
        def _decorated_dummy(x: int) -> int:
            """A decorated dummy tool."""
            return x

        self.assertIs(default_registry.get("_decorated_dummy"), _decorated_dummy)
        names = [s.name for s in default_registry.schemas()]
        self.assertIn("_decorated_dummy", names)


if __name__ == "__main__":
    unittest.main()
