import unittest

from state.backends.memory import InMemoryStateStore
from state.schema import StateSchema, SchemaError


class GetTests(unittest.TestCase):
    def test_missing_path_returns_default(self):
        store = InMemoryStateStore()
        self.assertIsNone(store.get("a.b.c"))
        self.assertEqual(store.get("a.b.c", default="fallback"), "fallback")

    def test_get_does_not_create_intermediate_layers(self):
        store = InMemoryStateStore()
        store.get("a.b.c")
        self.assertEqual(store.snapshot(), {})

    def test_get_nested_value(self):
        store = InMemoryStateStore(initial={"a": {"b": [1, 2, {"c": "x"}]}})
        self.assertEqual(store.get("a.b.2.c"), "x")


class PatchTests(unittest.TestCase):
    def test_patch_creates_missing_nested_dict(self):
        store = InMemoryStateStore()
        store.patch("a.b", "value")
        self.assertEqual(store.snapshot(), {"a": {"b": "value"}})

    def test_patch_merges_dicts_shallowly(self):
        store = InMemoryStateStore(initial={"a": {"x": 1, "y": 2}})
        store.patch("a", {"y": 20, "z": 3})
        self.assertEqual(store.snapshot(), {"a": {"x": 1, "y": 20, "z": 3}})

    def test_patch_replaces_scalar(self):
        store = InMemoryStateStore(initial={"a": 1})
        store.patch("a", 2)
        self.assertEqual(store.get("a"), 2)

    def test_patch_creates_list_for_digit_segment(self):
        store = InMemoryStateStore()
        store.patch("items.0", "first")
        self.assertEqual(store.snapshot(), {"items": ["first"]})

    def test_patch_list_append_at_end(self):
        store = InMemoryStateStore(initial={"items": ["a"]})
        store.patch("items.1", "b")
        self.assertEqual(store.get("items"), ["a", "b"])

    def test_patch_list_replace_existing_index(self):
        store = InMemoryStateStore(initial={"items": ["a", "b"]})
        store.patch("items.0", "z")
        self.assertEqual(store.get("items"), ["z", "b"])

    def test_patch_list_out_of_bounds_raises(self):
        store = InMemoryStateStore(initial={"items": []})
        with self.assertRaises(IndexError):
            store.patch("items.5", "x")

    def test_patch_wrong_type_for_digit_segment_raises(self):
        store = InMemoryStateStore(initial={"items": {"not": "a list"}})
        with self.assertRaises(TypeError):
            store.patch("items.0", "x")

    def test_patch_with_schema_validates(self):
        schema = StateSchema("s", {"n": int})
        store = InMemoryStateStore(schema=schema)
        store.patch("n", 5)
        with self.assertRaises(SchemaError):
            store.patch("n", "not an int")


class AppendTests(unittest.TestCase):
    def test_append_creates_list_if_missing(self):
        store = InMemoryStateStore()
        store.append("log", "entry1")
        self.assertEqual(store.get("log"), ["entry1"])

    def test_append_adds_to_existing_list(self):
        store = InMemoryStateStore(initial={"log": ["a"]})
        store.append("log", "b")
        self.assertEqual(store.get("log"), ["a", "b"])

    def test_append_to_non_list_raises(self):
        store = InMemoryStateStore(initial={"log": "not a list"})
        with self.assertRaises(TypeError):
            store.append("log", "x")

    def test_append_nested_path(self):
        store = InMemoryStateStore()
        store.append("story.chapters", {"title": "One"})
        self.assertEqual(store.get("story.chapters"), [{"title": "One"}])

    def test_append_with_schema_validates_element(self):
        schema = StateSchema("s", {"items": [int]})
        store = InMemoryStateStore(schema=schema)
        store.append("items", 1)
        with self.assertRaises(SchemaError):
            store.append("items", "not an int")


class SliceSnapshotLoadTests(unittest.TestCase):
    def test_slice_collects_multiple_paths(self):
        store = InMemoryStateStore(initial={"a": 1, "b": {"c": 2}})
        result = store.slice(["a", "b.c", "missing"])
        self.assertEqual(result, {"a": 1, "b.c": 2, "missing": None})

    def test_snapshot_is_deep_copy(self):
        store = InMemoryStateStore(initial={"a": {"b": [1, 2]}})
        snap = store.snapshot()
        snap["a"]["b"].append(3)
        self.assertEqual(store.get("a.b"), [1, 2])

    def test_load_replaces_state_and_deep_copies(self):
        store = InMemoryStateStore(initial={"a": 1})
        data = {"b": {"c": [1, 2]}}
        store.load(data)
        self.assertEqual(store.snapshot(), {"b": {"c": [1, 2]}})
        data["b"]["c"].append(3)
        self.assertEqual(store.get("b.c"), [1, 2])


if __name__ == "__main__":
    unittest.main()
