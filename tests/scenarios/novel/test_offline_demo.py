"""端到端验证 scenarios/novel 的完整接线(不需要真实 API Key)。

跑一遍 offline_demo.run_offline_demo,断言它真的驱动了 workflow.py 里拼出的
sequence -> loop -> checkpoint -> foreach(loop) -> sequence 这一整条链路,
并把结果落地成磁盘产物;顺带把第一章正文的内容钉住,防止后续改动
(比如误改了 ScriptedLLMClient 的响应顺序)悄悄丢掉这一版已经写完的正文。
"""

import json
import tempfile
import unittest
from pathlib import Path

from scenarios.novel.offline_demo import CHAPTER_1_TEXT, run_offline_demo


class OfflineDemoEndToEndTests(unittest.TestCase):
    def test_full_pipeline_lands_chapter_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "output"
            written = run_offline_demo(output_dir=output_dir)

            self.assertEqual(
                set(written), {"story_bible", "chapter_01", "manuscript"}
            )
            for path in written.values():
                self.assertTrue(path.exists(), f"{path} 应该被实际写到磁盘")

            bible = json.loads(written["story_bible"].read_text(encoding="utf-8"))
            meta = bible["story_bible"]["meta"]
            self.assertEqual(meta["title"], "凿空")
            self.assertTrue(meta["logline"])

            chapters = bible["story_bible"]["chapters"]
            self.assertEqual(len(chapters), 1)
            self.assertEqual(chapters[0]["title"], "初到西汉")
            self.assertEqual(chapters[0]["status"], "reviewed")
            self.assertEqual(chapters[0]["text"], CHAPTER_1_TEXT)
            self.assertGreater(chapters[0]["word_count"], 1000)

            foreshadowing = bible["story_bible"]["foreshadowing"]
            self.assertEqual(foreshadowing[0]["status"], "planted")

            chapter_md = written["chapter_01"].read_text(encoding="utf-8")
            self.assertIn("初到西汉", chapter_md)
            self.assertIn("苏亦", chapter_md)

            manuscript = written["manuscript"].read_text(encoding="utf-8")
            self.assertTrue(manuscript.startswith("# 凿空"))
            self.assertIn("初到西汉", manuscript)

    def test_pipeline_is_deterministic_across_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = run_offline_demo(output_dir=Path(tmp) / "run1")
            second = run_offline_demo(output_dir=Path(tmp) / "run2")
            self.assertEqual(
                first["chapter_01"].read_text(encoding="utf-8"),
                second["chapter_01"].read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
