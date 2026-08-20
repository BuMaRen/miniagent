import json

from bumaren_agent_workflow.engine.context import RunContext
from bumaren_agent_workflow.engine.stage import Stage
from scenarios.example.schemas.state import DRAFT_PATH, REVIEWED_PATH, DEPRECATED_PATH
from bumaren_agent_workflow.engine import Node


def build_testcase_output_node(output_path: str) -> Node:
    def _write(ctx: RunContext, inputs: dict) -> dict:
        # reads 声明的状态切片由 Stage.run 注入在 inputs["state"] 里(见
        # engine/stage.py Stage.run),不是直接摊平进 inputs 顶层。
        state = inputs.get("state", {})
        testcases = {
            "未审核用例": state.get(DRAFT_PATH, []),
            "审核通过的用例": state.get(REVIEWED_PATH, []),
            "已废弃的用例": state.get(DEPRECATED_PATH, []),
        }
        json_str = json.dumps(testcases, ensure_ascii=False, indent=2)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(json_str)
        return testcases

    return Stage(
        name="testcase_output",
        executor=_write,
        reads=[DRAFT_PATH, REVIEWED_PATH, DEPRECATED_PATH],
    )
