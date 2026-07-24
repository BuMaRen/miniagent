import unittest

from engine.context import ResumePoint, RunContext
from engine.primitives.checkpoint import Checkpoint, CheckpointPause
from engine.primitives.loop import OnExceed
from engine.stage import Stage
from engine.workflow import NodeRegistry, Workflow
from state.backends.memory import InMemoryStateStore


def _ctx(**kwargs):
    return RunContext(state=InMemoryStateStore(), **kwargs)


class _AddNode:
    def __init__(self, name, amount):
        self.name = name
        self.amount = amount

    def run(self, ctx, inputs):
        return {"value": inputs["value"] + self.amount}


class WorkflowRunTests(unittest.TestCase):
    def test_runs_top_level_nodes_in_order(self):
        wf = Workflow(name="wf", nodes=[_AddNode("a", 1), _AddNode("b", 2)])
        result = wf.run(_ctx(), {"value": 0})
        self.assertEqual(result, {"value": 3})

    def test_checkpoint_pause_bubbles_with_position_filled_in(self):
        wf = Workflow(
            name="wf",
            nodes=[_AddNode("a", 1), Checkpoint(name="cp"), _AddNode("b", 2)],
        )
        with self.assertRaises(CheckpointPause) as ctx_mgr:
            wf.run(_ctx(), {"value": 0})
        pause = ctx_mgr.exception
        self.assertEqual(pause.checkpoint_name, "cp")
        self.assertEqual(pause.node_index, 1)
        self.assertEqual(pause.inputs, {"value": 1})

    def test_resume_continues_from_checkpoint_node_index(self):
        wf = Workflow(
            name="wf",
            nodes=[_AddNode("a", 1), Checkpoint(name="cp"), _AddNode("b", 2)],
        )
        resume = ResumePoint(
            checkpoint_name="cp", node_index=1, inputs={"value": 1}, resume_input={}
        )
        result = wf.run(_ctx(resume=resume), {"value": 999})  # ignored: resume.inputs used
        self.assertEqual(result, {"value": 3})

    def test_workflow_events_emitted_to_trace(self):
        wf = Workflow(name="wf", nodes=[_AddNode("a", 1)])
        ctx = _ctx()
        wf.run(ctx, {"value": 0})
        events = [e["event"] for e in ctx.trace]
        self.assertEqual(events, ["workflow.start", "workflow.end"])


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

    def test_loop_keyword_requires_producer_critic_reviser(self):
        with self.assertRaises(ValueError):
            Workflow.from_spec(
                {"workflow": "wf", "stages": [{"loop": {"producer": "outline"}}]},
                self.registry,
            )

    def test_loop_keyword_builds_loop_with_options(self):
        wf = Workflow.from_spec(
            {
                "workflow": "wf",
                "stages": [
                    {
                        "loop": {
                            "producer": "outline",
                            "critic": "critic",
                            "reviser": "reviser",
                            "max_iterations": 5,
                            "on_exceed": "raise",
                        }
                    }
                ],
            },
            self.registry,
        )
        loop = wf.nodes[0]
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


if __name__ == "__main__":
    unittest.main()
