import unittest

from llm.providers.anthropic import AnthropicClient
from llm.providers.openai import OpenAIClient
from llm.providers.zhipu import ZhipuClient
from scenarios.essay.run import _infer_provider, build_llm_client


class InferProviderTests(unittest.TestCase):
    """_infer_provider 的 base_url 优先级是这条踩过坑的地方:base_url 指向
    OpenRouter 时,不管 model 长得像哪家的名字,都不能落回按前缀猜协议那条
    路——OpenRouter 的 /chat/completions 是 OpenAI 协议的直接兼容,不是
    Anthropic 官方 Messages API(实测通过 AnthropicClient 硬连 OpenRouter,
    会在工具调用的输出里泄漏 OpenRouter 内部模拟用的 XML 标签)。
    """

    def test_claude_prefixed_model_without_base_url_uses_anthropic(self):
        self.assertEqual(_infer_provider("claude-sonnet-4.5"), "anthropic")

    def test_glm_prefixed_model_uses_zhipu(self):
        self.assertEqual(_infer_provider("glm-5.2"), "zhipu")

    def test_unrecognized_prefix_falls_back_to_openai(self):
        self.assertEqual(_infer_provider("gpt-5"), "openai")

    def test_openrouter_base_url_wins_even_for_claude_prefixed_model(self):
        self.assertEqual(_infer_provider("claude-sonnet-5", base_url="https://openrouter.ai/api/v1"), "openai")

    def test_non_openrouter_base_url_does_not_affect_inference(self):
        self.assertEqual(
            _infer_provider("claude-sonnet-4.5", base_url="https://api.anthropic.com"), "anthropic"
        )


def _api_key_for(available: dict[str, str]):
    return lambda provider: available.get(provider)


class BuildLlmClientTests(unittest.TestCase):
    def test_openrouter_base_url_builds_openai_client_even_with_claude_model(self):
        client = build_llm_client(
            "claude-sonnet-5",
            api_key_for=_api_key_for({"openai": "k"}),
            base_url="https://openrouter.ai/api/v1",
        )
        self.assertIsInstance(client, OpenAIClient)
        self.assertNotIsInstance(client, AnthropicClient)

    def test_claude_model_without_openrouter_base_url_builds_anthropic_client(self):
        client = build_llm_client(
            "claude-sonnet-4.5", api_key_for=_api_key_for({"anthropic": "k"}), base_url=None
        )
        self.assertIsInstance(client, AnthropicClient)

    def test_glm_model_builds_zhipu_client(self):
        client = build_llm_client("glm-5.2", api_key_for=_api_key_for({"zhipu": "k"}), base_url=None)
        self.assertIsInstance(client, ZhipuClient)

    def test_unrecognized_model_builds_openai_client(self):
        client = build_llm_client("gpt-5", api_key_for=_api_key_for({"openai": "k"}), base_url=None)
        self.assertIsInstance(client, OpenAIClient)

    def test_openrouter_base_url_without_model_falls_back_to_openai_default(self):
        # model=None + openrouter base_url:provider 判成 openai,退回 openai
        # 的默认模型(gpt-4o)——不理想,但至少不会再被误判成 anthropic。
        client = build_llm_client(
            None, api_key_for=_api_key_for({"openai": "k"}), base_url="https://openrouter.ai/api/v1"
        )
        self.assertIsInstance(client, OpenAIClient)


if __name__ == "__main__":
    unittest.main()
