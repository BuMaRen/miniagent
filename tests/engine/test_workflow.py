import unittest

from bumaren_agent_workflow.engine.context import ResumePoint, RunContext
from bumaren_agent_workflow.engine.primitives.checkpoint import Checkpoint
from bumaren_agent_workflow.engine.workflow import Workflow, WorkflowFailure
from bumaren_agent_workflow.state.backends.memory import InMemoryStateStore


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



if __name__ == "__main__":
    unittest.main()
