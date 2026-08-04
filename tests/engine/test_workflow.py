import unittest

from engine.context import ResumePoint, RunContext
from engine.primitives.checkpoint import Checkpoint
from engine.primitives.loop import OnExceed
from engine.stage import Stage
from engine.workflow import NodeRegistry, Workflow, WorkflowFailure
from state.backends.memory import InMemoryStateStore


def _ctx(**kwargs):
    return RunContext(state=InMemoryStateStore(), **kwargs)


class _AddNode:
    def __init__(self, name, amount):
        self.name = name
        self.amount = amount

    def run(self, ctx, inputs):
        return {"value": inputs["value"] + self.amount}


class _BoomNode:
    """执行到就抛异常的节点,用于模拟"未预期的失败"(网络抖动/Provider 报错等)。"""

    def __init__(self, name, calls=None):
        self.name = name
        self.calls = calls if calls is not None else []

    def run(self, ctx, inputs):
        self.calls.append(inputs)
        raise RuntimeError("boom")


class WorkflowRunTests(unittest.TestCase):
    def test_runs_top_level_nodes_in_order(self):
        wf = Workflow(name="wf", nodes=[_AddNode("a", 1), _AddNode("b", 2)])
        result = wf.run(_ctx(), {"value": 0})
        self.assertEqual(result, {"value": 3})

    def test_checkpoint_without_handler_becomes_a_workflow_failure(self):
        # Checkpoint 不再有专属的暂停机制(见 engine.primitives.checkpoint 模块
        # docstring):缺 handler 就是一次普通异常,和其它节点失败一样被通用失败
        # 路径包成 WorkflowFailure,游标/inputs 回填逻辑完全一致。
        wf = Workflow(
            name="wf",
            nodes=[_AddNode("a", 1), Checkpoint(name="cp"), _AddNode("b", 2)],
        )
        with self.assertRaises(WorkflowFailure) as ctx_mgr:
            wf.run(_ctx(), {"value": 0})
        failure = ctx_mgr.exception
        self.assertEqual(failure.node_name, "cp")
        self.assertEqual(failure.node_index, 1)
        self.assertEqual(failure.inputs, {"value": 1})
        self.assertIsInstance(failure.__cause__, RuntimeError)

    def test_workflow_events_emitted_to_trace(self):
        wf = Workflow(name="wf", nodes=[_AddNode("a", 1)])
        ctx = _ctx()
        wf.run(ctx, {"value": 0})
        events = [e["event"] for e in ctx.trace]
        self.assertEqual(events, ["workflow.start", "workflow.end"])

    def test_unexpected_exception_bubbles_as_workflow_failure_with_position(self):
        wf = Workflow(
            name="wf",
            nodes=[_AddNode("a", 1), _BoomNode("boom"), _AddNode("b", 2)],
        )
        with self.assertRaises(WorkflowFailure) as ctx_mgr:
            wf.run(_ctx(), {"value": 0})
        failure = ctx_mgr.exception
        self.assertEqual(failure.node_name, "boom")
        self.assertEqual(failure.node_index, 1)
        self.assertEqual(failure.inputs, {"value": 1})
        # 原始异常保留在 __cause__ 上,不丢失诊断信息
        self.assertIsInstance(failure.__cause__, RuntimeError)

    def test_workflow_failed_event_emitted_to_trace(self):
        wf = Workflow(name="wf", nodes=[_BoomNode("boom")])
        ctx = _ctx()
        with self.assertRaises(WorkflowFailure):
            wf.run(ctx, {"value": 0})
        events = [e["event"] for e in ctx.trace]
        self.assertEqual(events, ["workflow.start", "workflow.failed"])

    def test_resume_after_failure_skips_completed_nodes_and_retries_failed_one(self):
        calls = []
        wf = Workflow(
            name="wf",
            nodes=[_AddNode("a", 1), _BoomNode("boom", calls=calls), _AddNode("b", 2)],
        )
        with self.assertRaises(WorkflowFailure) as ctx_mgr:
            wf.run(_ctx(), {"value": 0})
        failure = ctx_mgr.exception

        # 宿主据 WorkflowFailure 持久化后,下次运行构造一个 ResumePoint 续跑——
        # 这是唯一一条续跑通道,Checkpoint 失败也走它,不是另一套机制。
        resume = ResumePoint(node_index=failure.node_index, inputs=failure.inputs)
        replacement = Workflow(
            name="wf",
            nodes=[_AddNode("a", 1), _AddNode("fixed", 10), _AddNode("b", 2)],
        )
        result = replacement.run(_ctx(resume=resume), {"value": 999})
        # "a" 没有被再次调用(它的产出被直接复用作 resume.inputs);
        # 失败节点位置上的替代节点从 resume.inputs 开始正常执行。
        self.assertEqual(result, {"value": 13})


class NodeRegistryTests(unittest.TestCase):
    def test_register_and_get(self):
        registry = NodeRegistry()
        stage = Stage(name="s1", executor=lambda ctx, inputs: inputs)
        registry.register(stage)
        self.assertIs(registry.get("s1"), stage)

    def test_duplicate_registration_raises(self):
        registry = NodeRegistry()
        registry.register(Stage(name="s1", executor=lambda ctx, inputs: inputs))
        with self.assertRaises(ValueError):
            registry.register(Stage(name="s1", executor=lambda ctx, inputs: inputs))

    def test_missing_lookup_raises_keyerror_with_known_list(self):
        registry = NodeRegistry()
        registry.register(Stage(name="s1", executor=lambda ctx, inputs: inputs))
        with self.assertRaises(KeyError) as ctx_mgr:
            registry.get("nope")
        self.assertIn("s1", str(ctx_mgr.exception))

    def test_replace_swaps_the_node_and_returns_the_previous_one(self):
        # 典型用法:按声明式定义建好节点后,场景侧在外面包一层(见
        # scenarios/novel/stages.py 给评审节点补的状态写回)。
        registry = NodeRegistry()
        original = Stage(name="s1", executor=lambda ctx, inputs: inputs)
        registry.register(original)
        wrapper = Stage(name="s1", executor=lambda ctx, inputs: {"wrapped": True})
        self.assertIs(registry.replace(wrapper), original)
        self.assertIs(registry.get("s1"), wrapper)

    def test_replace_requires_the_name_to_exist(self):
        registry = NodeRegistry()
        with self.assertRaises(KeyError):
            registry.replace(Stage(name="nope", executor=lambda ctx, inputs: inputs))


class FromSpecTests(unittest.TestCase):
    def setUp(self):
        self.registry = NodeRegistry()
        self.registry.register(Stage(name="outline", executor=lambda ctx, i: {**i, "stage": "outline"}))
        self.registry.register(Stage(name="critic", executor=lambda ctx, i: {"passed": True, "feedback": ""}))
        self.registry.register(Stage(name="reviser", executor=lambda ctx, i: i))
        self.registry.register(Stage(name="write_chapter", executor=lambda ctx, i: i))

    def test_bare_string_references_registered_stage(self):
        wf = Workflow.from_spec({"workflow": "wf", "stages": ["outline"]}, self.registry)
        self.assertEqual(wf.name, "wf")
        self.assertEqual(len(wf.nodes), 1)
        self.assertIs(wf.nodes[0], self.registry.get("outline"))

    def test_sequence_keyword_builds_nested_nodes(self):
        wf = Workflow.from_spec(
            {"workflow": "wf", "stages": [{"sequence": ["outline", "reviser"]}]},
            self.registry,
        )
        self.assertEqual(len(wf.nodes), 1)
        seq = wf.nodes[0]
        self.assertEqual(len(seq.nodes), 2)

    def test_loop_keyword_requires_body_and_continue_when(self):
        with self.assertRaises(ValueError):
            Workflow.from_spec(
                {"workflow": "wf", "stages": [{"loop": {"body": ["outline"]}}]},
                self.registry,
            )

    def test_loop_body_must_be_a_list(self):
        with self.assertRaises(ValueError):
            Workflow.from_spec(
                {
                    "workflow": "wf",
                    "stages": [{"loop": {"body": "outline", "continue_when": "x.y"}}],
                },
                self.registry,
            )

    def test_loop_continue_when_must_be_a_state_path(self):
        with self.assertRaises(ValueError):
            Workflow.from_spec(
                {
                    "workflow": "wf",
                    "stages": [{"loop": {"body": ["outline"], "continue_when": ["x"]}}],
                },
                self.registry,
            )

    def test_loop_keyword_builds_loop_with_options(self):
        wf = Workflow.from_spec(
            {
                "workflow": "wf",
                "stages": [
                    {
                        "loop": {
                            "name": "review",
                            "body": ["outline", "critic", "reviser"],
                            "continue_when": "_loop.review.last.needs_revision",
                            "max_iterations": 5,
                            "on_exceed": "raise",
                        }
                    }
                ],
            },
            self.registry,
        )
        loop = wf.nodes[0]
        self.assertEqual([n.name for n in loop.body], ["outline", "critic", "reviser"])
        self.assertEqual(loop.continue_when, "_loop.review.last.needs_revision")
        self.assertEqual(loop.max_iterations, 5)
        self.assertEqual(loop.on_exceed, OnExceed.RAISE)

    def test_foreach_keyword_requires_items_path_and_body(self):
        with self.assertRaises(ValueError):
            Workflow.from_spec(
                {"workflow": "wf", "stages": [{"foreach": {"items_path": "chapters"}}]},
                self.registry,
            )

    def test_foreach_keyword_builds_node(self):
        wf = Workflow.from_spec(
            {
                "workflow": "wf",
                "stages": [
                    {"foreach": {"items_path": "chapters", "body": "write_chapter"}}
                ],
            },
            self.registry,
        )
        fe = wf.nodes[0]
        self.assertEqual(fe.items_path, "chapters")

    def test_checkpoint_keyword_str_form(self):
        wf = Workflow.from_spec(
            {"workflow": "wf", "stages": [{"checkpoint": "confirm"}]}, self.registry
        )
        cp = wf.nodes[0]
        self.assertEqual(cp.name, "confirm")

    def test_checkpoint_keyword_dict_form_requires_name(self):
        with self.assertRaises(ValueError):
            Workflow.from_spec(
                {"workflow": "wf", "stages": [{"checkpoint": {"prompt": "Approve?"}}]},
                self.registry,
            )

    def test_unknown_keyword_raises(self):
        with self.assertRaises(ValueError):
            Workflow.from_spec(
                {"workflow": "wf", "stages": [{"bogus": {}}]}, self.registry
            )

    def test_invalid_node_shape_raises(self):
        with self.assertRaises(ValueError):
            Workflow.from_spec({"workflow": "wf", "stages": [123]}, self.registry)

    def test_model_sibling_key_is_ignored_by_from_spec(self):
        # "model" 只供 resolve_stage_models 使用;from_spec 必须容忍它出现在
        # 原语关键字旁边,不当成"多出一个未知键"报错。
        wf = Workflow.from_spec(
            {
                "workflow": "wf",
                "stages": [{"sequence": ["outline", "reviser"], "model": "claude-sonnet-5"}],
            },
            self.registry,
        )
        self.assertEqual(len(wf.nodes[0].nodes), 2)


class ResolveStageModelsTests(unittest.TestCase):
    def test_no_model_anywhere_yields_empty_mapping(self):
        spec = {"workflow": "wf", "stages": ["outline", {"sequence": ["critic", "reviser"]}]}
        self.assertEqual(Workflow.resolve_stage_models(spec), {})

    def test_model_on_sequence_inherited_by_bare_string_children(self):
        spec = {
            "workflow": "wf",
            "stages": [{"sequence": ["outline", "critic"], "model": "claude-sonnet-5"}],
        }
        self.assertEqual(
            Workflow.resolve_stage_models(spec),
            {"outline": "claude-sonnet-5", "critic": "claude-sonnet-5"},
        )

    def test_child_stage_override_wins_over_inherited_model(self):
        spec = {
            "workflow": "wf",
            "stages": [
                {
                    "sequence": [
                        "outline",
                        {"stage": "critic", "model": "claude-haiku-4-5"},
                    ],
                    "model": "claude-sonnet-5",
                }
            ],
        }
        self.assertEqual(
            Workflow.resolve_stage_models(spec),
            {"outline": "claude-sonnet-5", "critic": "claude-haiku-4-5"},
        )

    def test_model_on_loop_propagates_into_body(self):
        spec = {
            "workflow": "wf",
            "stages": [
                {
                    "loop": {
                        "body": ["outline", "critic", "reviser"],
                        "continue_when": "_loop.loop_0.last.needs_revision",
                    },
                    "model": "claude-sonnet-5",
                }
            ],
        }
        self.assertEqual(
            Workflow.resolve_stage_models(spec),
            {
                "outline": "claude-sonnet-5",
                "critic": "claude-sonnet-5",
                "reviser": "claude-sonnet-5",
            },
        )

    def test_model_on_foreach_propagates_into_nested_body(self):
        spec = {
            "workflow": "wf",
            "stages": [
                {
                    "foreach": {
                        "items_path": "chapters",
                        "body": {
                            "loop": {
                                "body": ["outline", "critic", "reviser"],
                                "continue_when": "_loop.loop_0_body.last.needs_revision",
                            }
                        },
                    },
                    "model": "claude-sonnet-5",
                }
            ],
        }
        self.assertEqual(
            Workflow.resolve_stage_models(spec),
            {
                "outline": "claude-sonnet-5",
                "critic": "claude-sonnet-5",
                "reviser": "claude-sonnet-5",
            },
        )

    def test_nested_sequence_can_override_parent_model_for_its_own_subtree(self):
        spec = {
            "workflow": "wf",
            "stages": [
                {
                    "sequence": [
                        "outline",
                        {"sequence": ["critic", "reviser"], "model": "claude-haiku-4-5"},
                    ],
                    "model": "claude-sonnet-5",
                }
            ],
        }
        self.assertEqual(
            Workflow.resolve_stage_models(spec),
            {
                "outline": "claude-sonnet-5",
                "critic": "claude-haiku-4-5",
                "reviser": "claude-haiku-4-5",
            },
        )


if __name__ == "__main__":
    unittest.main()
