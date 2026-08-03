import json
import tempfile
import unittest
from pathlib import Path

from state.schema import (
    ANY,
    OneOf,
    SchemaError,
    SchemaRegistry,
    StateSchema,
    load_types,
)


class ValidateTests(unittest.TestCase):
    def test_any_accepts_anything(self):
        schema = StateSchema("s", {"x": ANY})
        schema.validate({"x": 123})
        schema.validate({"x": None})
        schema.validate({"x": [1, "two", {}]})

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

    def test_oneof_defaults_to_none(self):
        schema = StateSchema("s", {"y": OneOf("a", "b")})
        self.assertEqual(schema.empty(), {"y": None})

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


class FromYamlTests(unittest.TestCase):
    def _load(self, text: str) -> StateSchema:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "schema.yaml"
            path.write_text(text, encoding="utf-8")
            return StateSchema.from_yaml(path)

    def test_scalars_and_any(self):
        schema = self._load(
            """
            name: s
            definition:
              a: str
              b: int
              c: float
              d: bool
              e: any
            """
        )
        self.assertEqual(schema.name, "s")
        schema.validate({"a": "x", "b": 1, "c": 1.5, "d": True, "e": object()})
        with self.assertRaises(SchemaError):
            schema.validate({"a": 1})

    def test_list_and_nested_object(self):
        schema = self._load(
            """
            name: s
            definition:
              chapters:
                - index: int
                  title: str
            """
        )
        schema.validate({"chapters": [{"index": 1, "title": "One"}]})
        with self.assertRaises(SchemaError):
            schema.validate({"chapters": [{"index": "bad", "title": "One"}]})

    def test_inline_enum(self):
        schema = self._load(
            """
            name: s
            definition:
              payoff_chapter: int
              status:
                enum: [planted, resolved, dropped]
            """
        )
        schema.validate({"payoff_chapter": 3, "status": "resolved"})
        with self.assertRaises(SchemaError):
            schema.validate({"status": "nope"})

    def test_enum_value_must_be_a_list(self):
        with self.assertRaises(SchemaError):
            self._load(
                """
                name: s
                definition:
                  status:
                    enum: not_a_list
                """
            )

    def test_name_defaults_to_file_stem(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "my_schema.yaml"
            path.write_text("definition:\n  a: str\n", encoding="utf-8")
            schema = StateSchema.from_yaml(path)
        self.assertEqual(schema.name, "my_schema")

    def test_empty_and_to_json_schema_match_hand_built_definition(self):
        yaml_schema = self._load(
            """
            name: s
            definition:
              role:
                enum: [a, b]
              note: str
              items: [int]
            """
        )
        python_schema = StateSchema("s", {"role": OneOf("a", "b"), "note": str, "items": [int]})
        self.assertEqual(yaml_schema.empty(), python_schema.empty())
        self.assertEqual(yaml_schema.to_json_schema(), python_schema.to_json_schema())


class NamedTypesTests(unittest.TestCase):
    """裸名引用:既用来复用 types: 里的对象子结构,也用来引用具名枚举——两者是
    同一条查找规则(见 state/schema.py 的 _compile_yaml_node),不再需要
    !type/!oneof 这类标签来区分。
    """

    def _load(self, text: str) -> StateSchema:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "schema.yaml"
            path.write_text(text, encoding="utf-8")
            return StateSchema.from_yaml(path)

    def test_type_reference_resolves_to_earlier_declared_type(self):
        yaml_schema = self._load(
            """
            name: s
            types:
              character:
                id: str
                role:
                  enum: [protagonist, antagonist]
            definition:
              characters: [character]
            """
        )
        python_schema = StateSchema(
            "s", {"characters": [{"id": str, "role": OneOf("protagonist", "antagonist")}]}
        )
        self.assertEqual(yaml_schema.empty(), python_schema.empty())
        self.assertEqual(yaml_schema.to_json_schema(), python_schema.to_json_schema())

    def test_named_enum_can_be_declared_and_referenced_separately(self):
        yaml_schema = self._load(
            """
            name: s
            types:
              role_type:
                enum: [protagonist, antagonist]
              character:
                id: str
                role: role_type
            definition:
              characters: [character]
            """
        )
        python_schema = StateSchema(
            "s", {"characters": [{"id": str, "role": OneOf("protagonist", "antagonist")}]}
        )
        self.assertEqual(yaml_schema.empty(), python_schema.empty())
        self.assertEqual(yaml_schema.to_json_schema(), python_schema.to_json_schema())

    def test_type_can_reference_an_even_earlier_type_within_types_section(self):
        yaml_schema = self._load(
            """
            name: s
            types:
              relationship:
                target_id: str
              character:
                id: str
                relationships: [relationship]
            definition:
              characters: [character]
            """
        )
        yaml_schema.validate(
            {"characters": [{"id": "c1", "relationships": [{"target_id": "c2"}]}]}
        )
        with self.assertRaises(SchemaError):
            yaml_schema.validate({"characters": [{"id": "c1", "relationships": [{"bad": 1}]}]})

    def test_reference_to_undeclared_type_raises(self):
        with self.assertRaises(SchemaError):
            self._load(
                """
                name: s
                definition:
                  characters: [character]
                """
            )

    def test_reference_to_type_declared_later_raises(self):
        # 裸名引用只能指向前面已声明的类型:即便 "world" 在同一个 types: 段里,
        # 只要写在引用它的条目*之后*,编译时那张 registry 里还没有它。
        with self.assertRaises(SchemaError):
            self._load(
                """
                name: s
                types:
                  character:
                    home: world
                  world:
                    name: str
                definition:
                  characters: [character]
                """
            )

    def test_load_types_reused_across_files_via_types_param(self):
        with tempfile.TemporaryDirectory() as d:
            shared_path = Path(d) / "shared.yaml"
            shared_path.write_text(
                """
                types:
                  character:
                    id: str
                    name: str
                """,
                encoding="utf-8",
            )
            shared_types = load_types(shared_path)
            self.assertIn("character", shared_types)

            output_path = Path(d) / "output.yaml"
            output_path.write_text(
                """
                name: some_output
                definition:
                  people: [character]
                """,
                encoding="utf-8",
            )
            schema = StateSchema.from_yaml(output_path, types=shared_types)

        schema.validate({"people": [{"id": "1", "name": "A"}]})
        with self.assertRaises(SchemaError):
            schema.validate({"people": [{"id": "1", "unknown": True}]})


class ToPromptExampleTests(unittest.TestCase):
    def test_scalars_and_any(self):
        schema = StateSchema("s", {"a": str, "b": int, "c": float, "d": bool, "f": ANY})
        example = json.loads(schema.to_prompt_example())
        self.assertEqual(example, {"a": "...", "b": 0, "c": 0.0, "d": True, "f": "..."})

    def test_oneof_joins_choices_with_pipe(self):
        schema = StateSchema("s", {"role": OneOf("a", "b", "c")})
        example = json.loads(schema.to_prompt_example())
        self.assertEqual(example, {"role": "a|b|c"})

    def test_list_renders_single_example_element(self):
        schema = StateSchema("s", {"items": [{"id": str, "count": int}]})
        example = json.loads(schema.to_prompt_example())
        self.assertEqual(example, {"items": [{"id": "...", "count": 0}]})

    def test_none_definition_yields_empty_object(self):
        schema = StateSchema("s", None)
        self.assertEqual(schema.to_prompt_example(), "{}")


class SchemaRegistryTests(unittest.TestCase):
    """按名检索 schema——stages.yaml 里 `output_schema: critic_output` 就是走这张表。"""

    def setUp(self):
        self.registry = SchemaRegistry()
        self.schema = StateSchema("critic_output", {"needs_revision": bool})

    def test_register_then_get_by_name(self):
        self.assertTrue(self.registry.register(self.schema))
        self.assertIs(self.registry.get("critic_output"), self.schema)

    def test_duplicate_register_returns_false_and_keeps_the_first(self):
        self.registry.register(self.schema)
        self.assertFalse(self.registry.register(StateSchema("critic_output", {"x": int})))
        self.assertIs(self.registry.get("critic_output"), self.schema)

    def test_unknown_name_reports_the_registered_ones(self):
        self.registry.register(self.schema)
        with self.assertRaises(SchemaError) as caught:
            self.registry.get("nope")
        self.assertIn("critic_output", str(caught.exception))

    def test_load_dir_compiles_every_yaml_with_the_shared_types(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "shared.yaml").write_text(
                "types:\n  point:\n    x: int\n    y: int\ndefinition:\n  origin: point\n",
                encoding="utf-8",
            )
            # 名字取文件里的 name:,没写就取文件名;"point" 引用的是外部注入的类型表。
            (directory / "output.yaml").write_text(
                "name: stage_output\ndefinition:\n  where: point\n", encoding="utf-8"
            )
            types = load_types(directory / "shared.yaml")
            # 返回的是 schema 名(按文件名顺序:output.yaml 先于 shared.yaml)。
            self.assertEqual(self.registry.load_dir(directory, types=types), ["stage_output", "shared"])
        self.registry.get("stage_output").validate({"where": {"x": 1, "y": 2}})
        with self.assertRaises(SchemaError):
            self.registry.get("stage_output").validate({"where": {"x": "no"}})

    def test_load_dir_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "one.yaml").write_text("definition:\n  x: int\n", encoding="utf-8")
            self.assertEqual(self.registry.load_dir(directory), ["one"])
            self.assertEqual(self.registry.load_dir(directory), [])

    def test_missing_dir_is_an_error(self):
        with self.assertRaises(SchemaError):
            self.registry.load_dir("/nonexistent/schemas")


if __name__ == "__main__":
    unittest.main()
