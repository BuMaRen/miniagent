import unittest

from state.schema import ANY, OneOf, Optional, SchemaError, StateSchema


class ValidateTests(unittest.TestCase):
    def test_any_accepts_anything(self):
        schema = StateSchema("s", {"x": ANY})
        schema.validate({"x": 123})
        schema.validate({"x": None})
        schema.validate({"x": [1, "two", {}]})

    def test_optional_allows_none_or_inner(self):
        schema = StateSchema("s", {"x": Optional(int)})
        schema.validate({"x": None})
        schema.validate({"x": 3})
        with self.assertRaises(SchemaError):
            schema.validate({"x": "not an int"})

    def test_oneof_enforces_choices(self):
        schema = StateSchema("s", {"role": OneOf("a", "b", "c")})
        schema.validate({"role": "b"})
        with self.assertRaises(SchemaError):
            schema.validate({"role": "z"})

    def test_bool_is_not_int(self):
        schema = StateSchema("s", {"n": int})
        with self.assertRaises(SchemaError):
            schema.validate({"n": True})

    def test_float_accepts_int_but_not_bool(self):
        schema = StateSchema("s", {"f": float})
        schema.validate({"f": 3})
        schema.validate({"f": 3.5})
        with self.assertRaises(SchemaError):
            schema.validate({"f": True})

    def test_scalar_type_mismatch(self):
        schema = StateSchema("s", {"name": str})
        with self.assertRaises(SchemaError):
            schema.validate({"name": 123})

    def test_list_validates_each_element(self):
        schema = StateSchema("s", {"items": [int]})
        schema.validate({"items": [1, 2, 3]})
        with self.assertRaises(SchemaError):
            schema.validate({"items": [1, "bad", 3]})

    def test_list_rejects_non_list(self):
        schema = StateSchema("s", {"items": [int]})
        with self.assertRaises(SchemaError):
            schema.validate({"items": "not a list"})

    def test_dict_rejects_unknown_keys(self):
        schema = StateSchema("s", {"a": int})
        with self.assertRaises(SchemaError):
            schema.validate({"a": 1, "b": 2})

    def test_dict_allows_missing_keys(self):
        schema = StateSchema("s", {"a": int, "b": str})
        schema.validate({"a": 1})
        schema.validate({})

    def test_nested_object(self):
        schema = StateSchema(
            "s",
            {"characters": [{"id": str, "role": OneOf("protagonist", "antagonist")}]},
        )
        schema.validate({"characters": [{"id": "c1", "role": "protagonist"}]})
        with self.assertRaises(SchemaError):
            schema.validate({"characters": [{"id": "c1", "role": "villain"}]})

    def test_none_definition_means_no_validation(self):
        schema = StateSchema("s", None)
        schema.validate({"anything": "goes", "n": 1})


class EmptyTests(unittest.TestCase):
    def test_scalar_zero_values(self):
        schema = StateSchema("s", {"s": str, "i": int, "f": float, "b": bool})
        self.assertEqual(schema.empty(), {"s": "", "i": 0, "f": 0.0, "b": False})

    def test_list_defaults_to_empty_list(self):
        schema = StateSchema("s", {"items": [int]})
        self.assertEqual(schema.empty(), {"items": []})

    def test_optional_and_oneof_default_to_none(self):
        schema = StateSchema("s", {"x": Optional(int), "y": OneOf("a", "b")})
        self.assertEqual(schema.empty(), {"x": None, "y": None})

    def test_nested_object_recurses(self):
        schema = StateSchema("s", {"outer": {"inner": int}})
        self.assertEqual(schema.empty(), {"outer": {"inner": 0}})

    def test_none_definition_yields_empty_dict(self):
        schema = StateSchema("s", None)
        self.assertEqual(schema.empty(), {})


class ValidatePathTests(unittest.TestCase):
    def setUp(self):
        self.schema = StateSchema(
            "s",
            {
                "title": str,
                "chapters": [{"index": int, "title": str}],
            },
        )

    def test_top_level_scalar_path(self):
        self.schema.validate_path("title", "hello")
        with self.assertRaises(SchemaError):
            self.schema.validate_path("title", 123)

    def test_list_index_path(self):
        self.schema.validate_path("chapters.0.title", "Chapter One")
        with self.assertRaises(SchemaError):
            self.schema.validate_path("chapters.0.title", 123)

    def test_list_path_accepts_full_list_or_single_element(self):
        # append: single element
        self.schema.validate_path("chapters", {"index": 1, "title": "One"})
        # patch: full list
        self.schema.validate_path("chapters", [{"index": 1, "title": "One"}])

    def test_unknown_field_raises(self):
        with self.assertRaises(SchemaError):
            self.schema.validate_path("nope", 1)

    def test_indexing_non_list_raises(self):
        with self.assertRaises(SchemaError):
            self.schema.validate_path("title.0", "x")

    def test_none_definition_skips_validation(self):
        schema = StateSchema("s", None)
        schema.validate_path("anything.at.all", object())

    def test_any_subtree_unconstrained(self):
        schema = StateSchema("s", {"blob": ANY})
        schema.validate_path("blob.nested.path", "whatever")


class ToJsonSchemaTests(unittest.TestCase):
    def test_scalar_types(self):
        schema = StateSchema("s", {"s": str, "i": int, "f": float, "b": bool})
        self.assertEqual(
            schema.to_json_schema(),
            {
                "type": "object",
                "properties": {
                    "s": {"type": "string"},
                    "i": {"type": "integer"},
                    "f": {"type": "number"},
                    "b": {"type": "boolean"},
                },
                "required": ["s", "i", "f", "b"],
                "additionalProperties": False,
            },
        )

    def test_nested_object_and_list(self):
        schema = StateSchema("s", {"chapters": [{"index": int, "title": str}]})
        self.assertEqual(
            schema.to_json_schema(),
            {
                "type": "object",
                "properties": {
                    "chapters": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"index": {"type": "integer"}, "title": {"type": "string"}},
                            "required": ["index", "title"],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["chapters"],
                "additionalProperties": False,
            },
        )

    def test_optional_becomes_nullable_anyof(self):
        schema = StateSchema("s", {"x": Optional(int)})
        self.assertEqual(
            schema.to_json_schema(),
            {
                "type": "object",
                "properties": {"x": {"anyOf": [{"type": "integer"}, {"type": "null"}]}},
                "required": ["x"],
                "additionalProperties": False,
            },
        )

    def test_oneof_becomes_enum(self):
        schema = StateSchema("s", {"role": OneOf("a", "b", "c")})
        self.assertEqual(
            schema.to_json_schema()["properties"]["role"], {"enum": ["a", "b", "c"]}
        )

    def test_any_becomes_unconstrained_schema(self):
        schema = StateSchema("s", {"blob": ANY})
        self.assertEqual(schema.to_json_schema()["properties"]["blob"], {})

    def test_none_definition_yields_empty_schema(self):
        schema = StateSchema("s", None)
        self.assertEqual(schema.to_json_schema(), {})


if __name__ == "__main__":
    unittest.main()
