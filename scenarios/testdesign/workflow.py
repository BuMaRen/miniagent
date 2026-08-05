from typing import Callable

from engine.primitives.loop import Loop, OnExceed
from engine.workflow import Workflow
from engine.primitives import Sequence
from llm.client import LLMClient
from scenarios.testdesign.nodes.first_draft import build_first_draft_node
from scenarios.testdesign.nodes.pending_check import NEEDS_REDRAFT_KEY, build_pending_check_node
from scenarios.testdesign.nodes.redraft import build_redraft_node
from scenarios.testdesign.nodes.requirement_parse import build_requirement_parse_node
from scenarios.testdesign.nodes.review import build_review_node
from scenarios.testdesign.nodes.testcase_output import build_testcase_output_node
from scenarios.testdesign.schemas.state import TEST_DESIGN_STATE_SCHEMA

# args: stage_name, model_name
ClientFactory = Callable[[str, str | None], LLMClient]


def build_workflow(
    client_factory: ClientFactory, requirement_doc: str, testcase_output_path: str
) -> Workflow:
    """构建测试设计工作流。

    Args:
        client_factory: LLMClient 工厂函数,用于创建 LLMClient 实例。
        requirement_doc: 需求文档路径。
        testcase_output_path: 用例产出 JSON 的落地路径。

    Returns:
        Workflow: 测试设计工作流。
    """

    def client_for(stage_name: str, model: str | None = None) -> LLMClient:
        return client_factory(stage_name, model)

    nodes = [
        Sequence(
            name="test_case_first_draft",
            nodes=[
                build_requirement_parse_node(requirement_doc_path=requirement_doc),
                build_first_draft_node(client=client_for("first_draft")),
                build_review_node(client=client_for("review")),
            ],
        ),
        Loop(
            name="test_case_redraft_loop",
            # 真 = drafted_cases 仍非空、还要再来一轮 redraft+review(见
            # nodes/pending_check.py)。没有 checkpoint_handler,跑满
            # max_iterations 仍未收敛时直接接受最后一版,而不是升级成人工断点
            # ——workflow.md 里没有为这个流程设计任何人工介入点。
            continue_when=lambda ctx, outputs: outputs.get(NEEDS_REDRAFT_KEY, False),
            max_iterations=3,
            on_exceed=OnExceed.ACCEPT_LAST,
            body=[
                build_redraft_node(client=client_for("redraft")),
                build_review_node(client=client_for("review")),
                build_pending_check_node(),
            ],
        ),
        build_testcase_output_node(output_path=testcase_output_path),
    ]

    return Workflow(
        name="test_case_first_draft_workflow",
        nodes=nodes,
        state_schema=TEST_DESIGN_STATE_SCHEMA,
    )
