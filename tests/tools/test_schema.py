import unittest

from tools.schema import ToolSchema, schema_from_func


def sample_tool(x: int, y: str = "default") -> str:
    """Do a sample thing.

    Args:
        x: an integer argument.
        y: a string argument with a default.
    """
    return f"x={x}, y={y}"


def no_docstring_tool(a: bool, b: list, c: dict, d):
    return a, b, c, d


class SchemaFromFuncTests(unittest.TestCase):
    def test_name_and_description(self):
        schema = schema_from_func(sample_tool)
        self.assertEqual(schema.name, "sample_tool")
        self.assertEqual(schema.description, "Do a sample thing.")

    def test_required_vs_defaulted_params(self):
        schema = schema_from_func(sample_tool)
        self.assertIn("x", schema.parameters["required"])
        self.assertNotIn("y", schema.parameters["required"])
        self.assertEqual(schema.parameters["properties"]["y"]["default"], "default")

    def test_arg_descriptions_parsed_from_docstring(self):
        schema = schema_from_func(sample_tool)
        self.assertEqual(
            schema.parameters["properties"]["x"]["description"],
            "an integer argument.",
        )
        self.assertEqual(
            schema.parameters["properties"]["y"]["description"],
            "a string argument with a default.",
        )

    def test_type_mapping(self):
        schema = schema_from_func(sample_tool)
        self.assertEqual(schema.parameters["properties"]["x"]["type"], "integer")
        self.assertEqual(schema.parameters["properties"]["y"]["type"], "string")

    def test_all_supported_types_and_missing_docstring(self):
        schema = schema_from_func(no_docstring_tool)
        self.assertEqual(schema.description, "")
        props = schema.parameters["properties"]
        self.assertEqual(props["a"]["type"], "boolean")
        self.assertEqual(props["b"]["type"], "array")
        self.assertEqual(props["c"]["type"], "object")
        # unannotated param falls back to "string"
        self.assertEqual(props["d"]["type"], "string")
        self.assertEqual(
            set(schema.parameters["required"]), {"a", "b", "c", "d"}
        )


class ToolSchemaConversionTests(unittest.TestCase):
    def test_to_openai_shape(self):
        schema = ToolSchema(name="t", description="desc", parameters={"type": "object"})
        result = schema.to_openai()
        self.assertEqual(result["type"], "function")
        self.assertEqual(result["function"]["name"], "t")
        self.assertEqual(result["function"]["description"], "desc")
        self.assertEqual(result["function"]["parameters"], {"type": "object"})

    def test_to_anthropic_shape(self):
        schema = ToolSchema(name="t", description="desc", parameters={"type": "object"})
        result = schema.to_anthropic()
        self.assertEqual(result, {"name": "t", "description": "desc", "parameters": {"type": "object"}})


if __name__ == "__main__":
    unittest.main()
