"""engine/spec.py 的单测:把 stages.yaml 那样的声明式定义编译成 Node。

覆盖三件事:①"裸字符串 = 去注册表按名检索"这条引用规则对 executor/schema/toolset
都成立;② "@名字" 只用在 prompt 上,且输出格式示例由框架填;③ 配置写错时报的错
能定位到"哪个节点的哪个字段",并列出候选。
"""

import tempfile
import unittest
from pathlib import Path

from agent.toolset import ToolSet, ToolSetRegistry
from engine.context import RunContext
from engine.primitives.checkpoint import Checkpoint
from engine.spec import SpecError, build_node_registry, load_spec
from engine.stage import ExecutorRegistry, NodeWrapperRegistry, Stage
from prompts.registry import PromptRegistry
from state.backends.memory import InMemoryStateStore
from state.schema import SchemaRegistry, StateSchema


class FakeClient:
    """只用来被 Agent 持有,不真的发请求。"""

    def __init__(self, name: str, model: str | None) -> None:
        self.name = name
        self.model = model

    def chat(self, *args, **kwargs):  # pragma: no cover - 不该被调用
        raise NotImplementedError


def a_tool(x: int) -> int:
    """Double x.

    Args:
        x: 被翻倍的数。
    """
    return x * 2


class SpecTestCase(unittest.TestCase):
    """给每个用例一套独立的注册表,避免测试之间互相污染。"""

    def setUp(self):
        self.executors = ExecutorRegistry()
        self.prompts = PromptRegistry()
        self.schemas = SchemaRegistry()
        self.toolsets = ToolSetRegistry()
        self.wrappers = NodeWrapperRegistry()
        self.clients: list[FakeClient] = []

        self.executors.register("my_executor", lambda ctx, inputs: {"ok": True})
        self.prompts.register("style_guide", "【风格】现实主义")
        self.prompts.register("stage_prompt", "开头\n@style_guide\n\n输出格式:\n@output_schema_example")
        self.schemas.register(
            StateSchema(name="critic_output", definition={"needs_revision": bool, "feedback": str})
        )
        self.toolsets.register(ToolSet.from_funcs("research_toolset", [a_tool]))

    def client_factory(self, name, model):
        client = FakeClient(name, model)
        self.clients.append(client)
        return client

    def build(self, spec, **kwargs):
        return build_node_registry(
            spec,
            client_factory=self.client_factory,
            executors=self.executors,
            prompts=self.prompts,
            schemas=self.schemas,
            toolsets=self.toolsets,
            wrappers=self.wrappers,
            **kwargs,
        )

    def agent_of(self, node):
        """取出 Stage 背后的 Agent(executor 是它的 bound method)。"""
        return node.executor.__self__


class NamedExecutorTests(SpecTestCase):
    def test_bare_string_executor_is_looked_up_by_name(self):
        registry = self.build({"n": {"executor": "my_executor"}})
        node = registry.get("n")
        self.assertIsInstance(node, Stage)
        self.assertEqual(node.executor(None, {}), {"ok": True})

    def test_reads_writes_and_schemas_are_carried_over(self):
        registry = self.build(
            {
                "n": {
                    "executor": "my_executor",
                    "reads": ["a.b", "c"],
                    "writes": ["a.b"],
                    "input_schema": "critic_output",
                    "output_schema": "critic_output",
                }
            }
        )
        node = registry.get("n")
        self.assertEqual(node.reads, ("a.b", "c"))
        self.assertEqual(node.writes, ("a.b",))
        self.assertEqual(node.input_schema.name, "critic_output")
        self.assertEqual(node.output_schema.name, "critic_output")

    def test_a_single_path_may_be_written_without_the_list(self):
        registry = self.build({"n": {"executor": "my_executor", "reads": "a.b"}})
        self.assertEqual(registry.get("n").reads, ("a.b",))

    def test_no_client_is_built_for_a_plain_function_executor(self):
        self.build({"n": {"executor": "my_executor"}})
        self.assertEqual(self.clients, [])


class AgentExecutorTests(SpecTestCase):
    def _spec(self, **executor):
        return {"n": {"executor": {"prompt": "@stage_prompt", "output_schema": "critic_output", **executor}}}

    def test_dict_executor_builds_an_agent_with_the_resolved_prompt(self):
        registry = self.build(self._spec())
        agent = self.agent_of(registry.get("n"))
        self.assertEqual(
            agent.memory.system_prompt,
            '开头\n【风格】现实主义\n\n输出格式:\n{\n  "needs_revision": true,\n  "feedback": "..."\n}',
        )

    def test_literal_prompt_is_used_as_is_and_still_expands_references(self):
        registry = self.build(self._spec(prompt="自定义开头\n@style_guide"))
        agent = self.agent_of(registry.get("n"))
        self.assertTrue(agent.memory.system_prompt.startswith("自定义开头\n【风格】现实主义"))

    def test_output_format_is_appended_when_the_prompt_has_no_placeholder(self):
        self.prompts.register("bare", "没有占位符")
        registry = self.build(self._spec(prompt="@bare"))
        prompt = self.agent_of(registry.get("n")).memory.system_prompt
        self.assertTrue(prompt.startswith("没有占位符"))
        self.assertIn('"needs_revision"', prompt)

    def test_toolsets_are_mounted_by_name(self):
        registry = self.build(self._spec(tools=["research"]))
        agent = self.agent_of(registry.get("n"))
        self.assertEqual([s.name for s in agent.registry.schemas()], ["a_tool"])

    def test_each_agent_gets_its_own_tool_registry(self):
        registry = self.build(
            {
                "with_tools": {"executor": {"prompt": "@stage_prompt", "output_schema": "critic_output", "tools": ["research"]}},
                "without_tools": {"executor": {"prompt": "@stage_prompt", "output_schema": "critic_output"}},
            }
        )
        self.assertEqual(self.agent_of(registry.get("without_tools")).registry.schemas(), [])

    def test_agent_output_schema_is_reused_as_the_stage_contract(self):
        registry = self.build(self._spec())
        node = registry.get("n")
        self.assertEqual(node.output_schema.name, "critic_output")
        self.assertIs(node.output_schema, self.agent_of(node).output_schema)

    def test_node_level_output_schema_reaches_the_agent(self):
        registry = self.build({"n": {"executor": {"prompt": "@stage_prompt"}, "output_schema": "critic_output"}})
        self.assertEqual(self.agent_of(registry.get("n")).output_schema.name, "critic_output")

    def test_defaults_fill_in_missing_executor_fields(self):
        spec = self._spec()
        spec["defaults"] = {"executor": {"max_steps": 3}}
        registry = self.build(spec)
        self.assertEqual(self.agent_of(registry.get("n")).max_steps, 3)

    def test_node_overrides_the_defaults(self):
        spec = self._spec(max_steps=5)
        spec["defaults"] = {"executor": {"max_steps": 3}}
        registry = self.build(spec)
        self.assertEqual(self.agent_of(registry.get("n")).max_steps, 5)

    def test_defaults_is_not_treated_as_a_node(self):
        spec = self._spec()
        spec["defaults"] = {"executor": {"max_steps": 3}}
        registry = self.build(spec)
        with self.assertRaises(KeyError):
            registry.get("defaults")


class ModelResolutionTests(SpecTestCase):
    def _spec(self, **executor):
        return {"n": {"executor": {"prompt": "@stage_prompt", "output_schema": "critic_output", **executor}}}

    def test_the_node_model_is_passed_to_the_client_factory(self):
        self.build(self._spec(model="from-stages"))
        self.assertEqual((self.clients[0].name, self.clients[0].model), ("n", "from-stages"))

    def test_workflow_annotation_wins_over_the_node_default(self):
        # 编排层(workflow.yaml)标注/继承下来的 model 优先于节点自带的默认值。
        self.build(self._spec(model="from-stages"), stage_models={"n": "from-workflow"})
        self.assertEqual(self.clients[0].model, "from-workflow")

    def test_no_model_anywhere_means_none(self):
        self.build(self._spec())
        self.assertIsNone(self.clients[0].model)


class CheckpointTests(SpecTestCase):
    def test_checkpoint_node_is_built_with_its_prompt_and_schema(self):
        registry = self.build(
            {"cp": {"checkpoint": {"prompt": "确认?", "resume_input_schema": "critic_output"}}}
        )
        node = registry.get("cp")
        self.assertIsInstance(node, Checkpoint)
        self.assertEqual(node.name, "cp")
        self.assertEqual(node.prompt, "确认?")
        self.assertEqual(node.resume_input_schema.name, "critic_output")

    def test_checkpoint_may_be_declared_empty(self):
        registry = self.build({"cp": {"checkpoint": None}})
        node = registry.get("cp")
        self.assertIsNone(node.prompt)
        self.assertIsNone(node.resume_input_schema)

    def test_checkpoint_prompt_can_also_be_a_reference(self):
        self.prompts.register("ask", "请确认")
        registry = self.build({"cp": {"checkpoint": {"prompt": "@ask"}}})
        self.assertEqual(registry.get("cp").prompt, "请确认")


class _TaggingNode:
    """薄包装:name 与内层节点一致(与 scenarios/novel/executors.py 里的真实包装
    同构),run() 的输出多打一个标签,用来在测试里断言"确实被包过"。
    """

    def __init__(self, node, tag: str) -> None:
        self._node = node
        self.name = node.name
        self._tag = tag

    def run(self, ctx, inputs):
        outputs = dict(self._node.run(ctx, inputs))
        outputs.setdefault("tags", []).append(self._tag)
        return outputs


class WrapTests(SpecTestCase):
    """节点建好后按 `wrap:` 声明套一层包装(见 engine/stage.py 的 node_wrapper)。"""

    def setUp(self):
        super().setUp()
        self.wrappers.register("tag_a", lambda node: _TaggingNode(node, "a"))
        self.wrappers.register("tag_b", lambda node: _TaggingNode(node, "b"))
        self.ctx = RunContext(state=InMemoryStateStore())

    def test_wrap_applies_a_registered_wrapper_after_building_a_stage(self):
        registry = self.build({"n": {"executor": "my_executor", "wrap": "tag_a"}})
        node = registry.get("n")
        self.assertEqual(node.name, "n")
        self.assertEqual(node.run(self.ctx, {}), {"ok": True, "tags": ["a"]})

    def test_wrap_applies_a_registered_wrapper_after_building_a_checkpoint(self):
        registry = self.build({"cp": {"checkpoint": {"prompt": "确认?"}, "wrap": "tag_a"}})
        node = registry.get("cp")
        self.assertEqual(node.name, "cp")
        self.assertIsInstance(node, _TaggingNode)

    def test_wrap_list_applies_wrappers_in_order(self):
        registry = self.build(
            {"n": {"executor": "my_executor", "wrap": ["tag_a", "tag_b"]}}
        )
        self.assertEqual(registry.get("n").run(self.ctx, {})["tags"], ["a", "b"])

    def test_no_wrap_leaves_the_node_untouched(self):
        registry = self.build({"n": {"executor": "my_executor"}})
        self.assertNotIsInstance(registry.get("n"), _TaggingNode)

    def test_unknown_wrapper_name_lists_candidates(self):
        with self.assertRaises(SpecError) as caught:
            self.build({"n": {"executor": "my_executor", "wrap": "nope"}})
        message = str(caught.exception)
        self.assertIn("'n'", message)
        self.assertIn("tag_a", message)


class ErrorReportingTests(SpecTestCase):
    def assert_spec_error(self, spec, *fragments):
        with self.assertRaises(SpecError) as caught:
            self.build(spec)
        message = str(caught.exception)
        for fragment in fragments:
            self.assertIn(fragment, message)

    def test_unknown_node_field(self):
        self.assert_spec_error({"n": {"executorr": "my_executor"}}, "'n'", "executorr")

    def test_missing_executor(self):
        self.assert_spec_error({"n": {"reads": ["a"]}}, "'n'", "executor")

    def test_unknown_executor_name_lists_candidates(self):
        self.assert_spec_error({"n": {"executor": "nope"}}, "'n'", "my_executor")

    def test_unknown_schema_name_lists_candidates(self):
        self.assert_spec_error(
            {"n": {"executor": "my_executor", "output_schema": "nope"}}, "'n'", "critic_output"
        )

    def test_unknown_prompt_lists_candidates(self):
        self.assert_spec_error(
            {"n": {"executor": {"prompt": "@nope", "output_schema": "critic_output"}}},
            "'n'",
            "stage_prompt",
        )

    def test_unknown_toolset_lists_candidates(self):
        self.assert_spec_error(
            {
                "n": {
                    "executor": {
                        "prompt": "@stage_prompt",
                        "output_schema": "critic_output",
                        "tools": ["nope"],
                    }
                }
            },
            "'n'",
            "research_toolset",
        )

    def test_agent_without_output_schema(self):
        self.assert_spec_error({"n": {"executor": {"prompt": "@stage_prompt"}}}, "output_schema")

    def test_agent_without_prompt(self):
        self.assert_spec_error({"n": {"executor": {"output_schema": "critic_output"}}}, "prompt")

    def test_unknown_agent_field(self):
        self.assert_spec_error(
            {"n": {"executor": {"prompt": "@stage_prompt", "output_schema": "critic_output", "tool": []}}},
            "tool",
        )

    def test_checkpoint_and_executor_are_mutually_exclusive(self):
        self.assert_spec_error({"n": {"executor": "my_executor", "checkpoint": {}}}, "二选一")

    def test_agent_without_a_client_factory(self):
        with self.assertRaises(SpecError) as caught:
            build_node_registry(
                {"n": {"executor": {"prompt": "@stage_prompt", "output_schema": "critic_output"}}},
                prompts=self.prompts,
                schemas=self.schemas,
                toolsets=self.toolsets,
            )
        self.assertIn("client_factory", str(caught.exception))


class LoadSpecTests(SpecTestCase):
    def test_yaml_path_is_accepted_directly(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "stages.yaml"
            # "@" 是 YAML 保留指示符,必须加引号——这正是 stages.yaml 里的写法。
            path.write_text(
                'n:\n  executor:\n    prompt: "@stage_prompt"\n'
                "    output_schema: critic_output\n  reads:\n    - a.b\n",
                encoding="utf-8",
            )
            self.assertIn("n", load_spec(path))
            registry = self.build(path)
        self.assertEqual(registry.get("n").reads, ("a.b",))

    def test_unquoted_at_is_not_valid_yaml(self):
        import yaml

        with self.assertRaises(yaml.YAMLError):
            yaml.safe_load("n:\n  executor:\n    prompt: @stage_prompt\n")


if __name__ == "__main__":
    unittest.main()
