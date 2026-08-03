"""build_node_registry 把 workflow.yaml 解析出的 stage_models 转给 client_factory
这条接线的单测(见 engine.workflow.Workflow.resolve_stage_models 与
engine.scenario.Scenario.build_workflow)。

现在每个节点在 workflow.yaml 里都以自己的名字出现(评审的"多道关卡"是 Loop 的
body 直接列出来的,不再包进场景侧的组合节点),所以 stage_models 的键和
client_factory 查的名字天然一致,不需要任何换名——这里就是把这件事钉住。
"""

import unittest

from scenarios.novel import SCENARIO


class BuildNodeRegistryStageModelsTests(unittest.TestCase):
    def _factory_and_calls(self):
        calls: dict[str, str | None] = {}

        def factory(stage_name, model):
            calls[stage_name] = model
            return object()

        return factory, calls

    def test_stage_names_matching_yaml_tree_get_their_model_directly(self):
        factory, calls = self._factory_and_calls()
        SCENARIO.build_node_registry(
            factory,
            stage_models={
                "concept_expansion": "claude-sonnet-5",
                "outline_generation": "claude-sonnet-5",
            },
        )
        self.assertEqual(calls["concept_expansion"], "claude-sonnet-5")
        self.assertEqual(calls["outline_generation"], "claude-sonnet-5")
        self.assertIsNone(calls["character_world_design"])

    def test_critics_resolve_under_their_own_names(self):
        factory, calls = self._factory_and_calls()
        SCENARIO.build_node_registry(
            factory,
            stage_models={
                "outline_critic": "claude-sonnet-5",
                "chapter_critic": "claude-haiku-4-5",
            },
        )
        self.assertEqual(calls["outline_critic"], "claude-sonnet-5")
        self.assertEqual(calls["chapter_critic"], "claude-haiku-4-5")

    def test_no_stage_models_means_every_call_gets_none(self):
        factory, calls = self._factory_and_calls()
        SCENARIO.build_node_registry(factory)
        self.assertTrue(all(model is None for model in calls.values()))


if __name__ == "__main__":
    unittest.main()
