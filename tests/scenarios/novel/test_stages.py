"""build_node_registry 把 workflow.yaml 解析出的 stage_models 转给 client_factory
这条接线的单测(见 engine.workflow.Workflow.resolve_stage_models 与
scenarios.novel.workflow.build_workflow)。

重点验证:outline_critic/chapter_critic 这两个 Stage 在 workflow.yaml 里从不以
自己的名字出现——它们被包进 ReviewChain,注册与被引用的都是 "outline_review"/
"chapter_review" 这个复合名字——client_factory 收到的仍应是 stage_models 里以
复合名字为键解析出的那个 model,而不是 None。
"""

import unittest

from scenarios.novel.stages import build_node_registry


class BuildNodeRegistryStageModelsTests(unittest.TestCase):
    def _factory_and_calls(self):
        calls: dict[str, str | None] = {}

        def factory(stage_name, model):
            calls[stage_name] = model
            return object()

        return factory, calls

    def test_stage_names_matching_yaml_tree_get_their_model_directly(self):
        factory, calls = self._factory_and_calls()
        build_node_registry(
            factory,
            stage_models={
                "concept_expansion": "claude-sonnet-5",
                "outline_generation": "claude-sonnet-5",
            },
        )
        self.assertEqual(calls["concept_expansion"], "claude-sonnet-5")
        self.assertEqual(calls["outline_generation"], "claude-sonnet-5")
        self.assertIsNone(calls["character_world_design"])

    def test_outline_and_chapter_critic_resolve_via_composite_review_chain_name(self):
        factory, calls = self._factory_and_calls()
        build_node_registry(
            factory,
            stage_models={
                "outline_review": "claude-sonnet-5",
                "chapter_review": "claude-haiku-4-5",
            },
        )
        self.assertEqual(calls["outline_critic"], "claude-sonnet-5")
        self.assertEqual(calls["chapter_critic"], "claude-haiku-4-5")

    def test_no_stage_models_means_every_call_gets_none(self):
        factory, calls = self._factory_and_calls()
        build_node_registry(factory)
        self.assertTrue(all(model is None for model in calls.values()))


if __name__ == "__main__":
    unittest.main()
