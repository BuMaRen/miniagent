import json

from engine.context import RunContext
from engine.stage import Stage
from scenarios.testdesign.schemas.state import DRAFT_PATH, REVIEW_PATH, DEPRECATED_PATH
from engine import Node


def build_testcase_output_node(output_path: str) -> Node:
    def _write(ctx: RunContext, inputs: dict) -> dict:
        testcases = {
            "未审核用例": inputs.get(DRAFT_PATH, []),
            "审核通过的用例": inputs.get(REVIEW_PATH, []),
            "已废弃的用例": inputs.get(DEPRECATED_PATH, []),
        }
        json_str = json.dumps(testcases, ensure_ascii=False, indent=2)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(json_str)
        return testcases

    return Stage(
        name="testcase_output",
        executor=_write,
        reads=[DRAFT_PATH, REVIEW_PATH, DEPRECATED_PATH],
    )
