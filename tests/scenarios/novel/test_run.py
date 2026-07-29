"""build_llm_client 的 Provider 路由测试(scenarios/novel/run.py)。

重点验证:显式指定 model 时,Provider 由模型名本身决定(claude-* 只能走
Anthropic SDK),而不是"哪个 API Key 环境变量恰好存在"——这两者一旦不一致
(比如只设置了 OPENAI_API_KEY,却要求某个节点用 claude-sonnet-5),必须直接
报错,而不是把 claude 模型名悄悄发去 OpenAI 的接口。
"""

import os
import unittest
from unittest.mock import patch

from scenarios.novel.run import _infer_provider, build_llm_client


class InferProviderTests(unittest.TestCase):
    def test_claude_models_map_to_anthropic(self):
        self.assertEqual(_infer_provider("claude-sonnet-5"), "anthropic")
        self.assertEqual(_infer_provider("claude-haiku-4-5-20251001"), "anthropic")

    def test_non_claude_models_map_to_openai(self):
        self.assertEqual(_infer_provider("gpt-4o"), "openai")


class BuildLlmClientProviderRoutingTests(unittest.TestCase):
    def test_explicit_claude_model_with_only_openai_key_raises(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=True):
            with self.assertRaises(RuntimeError) as cm:
                build_llm_client(model="claude-sonnet-5")
        self.assertIn("ANTHROPIC_API_KEY", str(cm.exception))

    def test_explicit_gpt_model_with_only_anthropic_key_raises(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-test"}, clear=True):
            with self.assertRaises(RuntimeError) as cm:
                build_llm_client(model="gpt-4o")
        self.assertIn("OPENAI_API_KEY", str(cm.exception))

    def test_explicit_claude_model_with_anthropic_key_builds_anthropic_client(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-test"}, clear=True):
            client = build_llm_client(model="claude-sonnet-5")
        from llm.providers.anthropic import AnthropicClient

        self.assertIsInstance(client, AnthropicClient)
        self.assertEqual(client._model, "claude-sonnet-5")

    def test_no_model_falls_back_to_whichever_key_is_present(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-test"}, clear=True):
            client = build_llm_client()
        from llm.providers.anthropic import AnthropicClient

        self.assertIsInstance(client, AnthropicClient)
        self.assertEqual(client._model, "claude-sonnet-4-5")

    def test_no_model_and_no_keys_raises(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                build_llm_client()


if __name__ == "__main__":
    unittest.main()
