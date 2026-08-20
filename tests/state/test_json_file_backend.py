import json
import tempfile
import unittest
from pathlib import Path

from bumaren_agent_workflow.state.backends.json_file import JsonFileStateStore


class JsonFileStateStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.path = Path(self._tmpdir.name) / "state.json"

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_starts_empty_when_no_file(self):
        store = JsonFileStateStore(self.path)
        self.assertEqual(store.snapshot(), {})
        self.assertFalse(self.path.exists())

    def test_patch_persists_to_disk(self):
        store = JsonFileStateStore(self.path)
        store.patch("title", "My Story")
        with self.path.open() as f:
            data = json.load(f)
        self.assertEqual(data, {"title": "My Story"})

    def test_append_persists_to_disk(self):
        store = JsonFileStateStore(self.path)
        store.append("log", "entry")
        with self.path.open() as f:
            data = json.load(f)
        self.assertEqual(data, {"log": ["entry"]})

    def test_reload_picks_up_persisted_state(self):
        store = JsonFileStateStore(self.path)
        store.patch("a.b", 1)
        store.append("log", "x")

        reloaded = JsonFileStateStore(self.path)
        self.assertEqual(reloaded.get("a.b"), 1)
        self.assertEqual(reloaded.get("log"), ["x"])

    def test_load_overwrites_and_persists(self):
        store = JsonFileStateStore(self.path)
        store.patch("old", 1)
        store.load({"new": 2})

        reloaded = JsonFileStateStore(self.path)
        self.assertEqual(reloaded.snapshot(), {"new": 2})

    def test_creates_parent_directories(self):
        nested = Path(self._tmpdir.name) / "nested" / "dir" / "state.json"
        store = JsonFileStateStore(nested)
        store.patch("a", 1)
        self.assertTrue(nested.exists())

    def test_no_leftover_tmp_file_after_flush(self):
        store = JsonFileStateStore(self.path)
        store.patch("a", 1)
        tmp_path = self.path.with_name(self.path.name + ".tmp")
        self.assertFalse(tmp_path.exists())


if __name__ == "__main__":
    unittest.main()
