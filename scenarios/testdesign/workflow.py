from typing import Callable

from engine.primitives.breaker import Breaker
from engine.primitives.loop import Loop
from engine.workflow import Workflow
from engine.primitives import Sequence
from llm.client import LLMClient
from scenarios.testdesign.nodes.first_draft import build_first_draft_node
from scenarios.testdesign.nodes.redraft import build_redraft_node
from scenarios.testdesign.nodes.requirement_parse import build_requirement_parse_node
from scenarios.testdesign.nodes.review import build_review_node
from scenarios.testdesign.nodes.testcase_output import build_testcase_output_node
from scenarios.testdesign.schemas.state import (
    DRAFT_KEY,
    DRAFT_PATH,
    TEST_DESIGN_STATE_SCHEMA,
)

# args: stage_name, model_name
ClientFactory = Callable[[str, str | None], LLMClient]


def build_workflow(
    client_factory: ClientFactory, requirement_doc: str, testcase_output_path: str
) -> Workflow:
    """构建测试设计工作流。

    Args:
        client_factory: LLMClient 工厂函数,用于创建 LLMClient 实例。
        requirement_doc: 测试需求文档。

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
            continue_when=lambda _, inputs: len(inputs.get(DRAFT_PATH, [])) == 0,
            max_iterations=3,
            body=[
                build_redraft_node(client=client_for("redraft")),
                build_review_node(client=client_for("review")),
                Breaker(
                    name="loop_breaker",
                    predicate=lambda _, inputs: len(inputs.get(DRAFT_PATH, [])) == 0,
                ),
            ],
        ),
        build_testcase_output_node(output_path=testcase_output_path),
    ]

    return Workflow(
        name="test_case_first_draft_workflow",
        nodes=nodes,
        state_schema=TEST_DESIGN_STATE_SCHEMA,
    )
