from typing import Callable

from engine.primitives import Breaker, Checkpoint, Continuer, Loop, OnExceed, Sequence
from engine.stage import Node
from engine.workflow import Workflow
from llm.client import LLMClient
from llm.image_client import ImageClient
from scenarios.essay.nodes.cover import build_cover_brief_node, build_cover_image_node
from scenarios.essay.nodes.drafting import build_first_draft_node, build_redraft_node
from scenarios.essay.nodes.meta import build_meta_node
from scenarios.essay.nodes.planning import PLANNING_CHECKPOINT_LOOP_NAME, build_planning_node
from scenarios.essay.nodes.review import build_review_node
from scenarios.essay.schemas.state import APPROVAL_SCHEMA, ESSAY_STATE_SCHEMA, REVIEW_PATH

REDRAFT_LOOP_NAME = "redraft_loop"

# args: stage_name, model_name
ClientFactory = Callable[[str, str | None], LLMClient]


def _build_planning_stage(client_factory: ClientFactory, human_review: bool) -> Node:
    planning = build_planning_node(client=client_factory("planning", None))
    if not human_review:
        # 需求原话:"不勾选则全程由 AI 编写审核",情节规划这个节点本身不接
        # AI 审核,所以不勾选人工审核时直接跑一次规划,没有任何复核环节。
        return planning

    return Loop(
        name=PLANNING_CHECKPOINT_LOOP_NAME,
        # 初次 + 最多 2 次返工 = 3 轮;第 3 轮仍被驳回则终止任务(需求原话:
        # "人工审核只会返工最多 2 次,如果用户仍未同意则终止任务")。
        max_iterations=3,
        on_exceed=OnExceed.RAISE,
        body=[
            planning,
            Checkpoint(
                name="confirm_planning",
                prompt="情节规划已完成,请确认是否可以据此进入正文编撰;如需修改请在反馈里说明理由。",
                resume_input_schema=APPROVAL_SCHEMA,
            ),
            Continuer(
                name="planning_rejected",
                predicate=lambda ctx, outputs: not outputs.get("approved", False),
            ),
        ],
    )


def build_workflow(
    client_factory: ClientFactory,
    image_client: ImageClient,
    human_review: bool,
    generate_cover: bool,
) -> Workflow:
    """构建短篇小说生产工作流。

    Args:
        client_factory: LLMClient 工厂函数,签名 (stage_name, model) -> LLMClient。
                        "cover" 是独立的 stage_name(有自己的 model/base_url/
                        api_key,不再复用 "drafting" 的),供调用方按需为每个
                        环节挑更便宜的模型。
        image_client:   封面图像生成客户端(占位实现见 llm.image_client.NotConfiguredImageClient)。
                        generate_cover=False 时不会被调用。
        human_review:   是否在情节规划完成后接入人工审核 Checkpoint(对应
                        brief.human_review,由调用方在构建期决定,不在运行期读)。
        generate_cover: 是否生成封面(对应 brief.generate_cover)。封面是可选
                        功能——不是每个故事都需要,关掉时直接不接这两个节点,
                        不产生任何额外的模型调用。标题/简介/分类标签
                        (meta 节点)不受这个开关影响,始终执行——它们是
                        每篇产出都要有的展示信息,不是可选功能。

    Returns:
        Workflow: 短篇小说生产工作流。
    """

    nodes: list[Node] = [
        _build_planning_stage(client_factory, human_review),
        Sequence(
            name="first_pass",
            nodes=[
                build_first_draft_node(client=client_factory("drafting", None)),
                build_review_node(client=client_factory("review", None)),
            ],
        ),
        Loop(
            name=REDRAFT_LOOP_NAME,
            max_iterations=2,
            # 没有人工介入(需求文档没有为审核/改稿环节设计任何人工断点),
            # 不能用 ESCALATE_TO_CHECKPOINT——没有人在等着裁决。
            on_exceed=OnExceed.ACCEPT_LAST,
            body=[
                # first_pass 的审核已经通过时,不必再白跑一轮 redraft+review
                # (照抄 scenarios/example/workflow.py 的 pending_check 短路模式)。
                Breaker(
                    name="already_accepted",
                    predicate=lambda ctx, _inputs: not ctx.state.get(REVIEW_PATH, {}).get("rejected", False),
                ),
                build_redraft_node(client=client_factory("drafting", None)),
                build_review_node(client=client_factory("review", None)),
                Continuer(
                    name="pending_revision",
                    predicate=lambda ctx, _outputs: bool(ctx.state.get(REVIEW_PATH, {}).get("rejected", False)),
                ),
            ],
        ),
        build_meta_node(client=client_factory("meta", None)),
    ]

    if generate_cover:
        nodes.append(build_cover_brief_node(client=client_factory("cover", None)))
        nodes.append(build_cover_image_node(image_client))

    return Workflow(name="essay_workflow", nodes=nodes, state_schema=ESSAY_STATE_SCHEMA)
