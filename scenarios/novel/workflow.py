"""在 Python 里直接拼出 novel_generation 的 Workflow(外层组装)。

每个 Node 是什么由 scenarios/novel/nodes/ 下按业务分组的模块各自负责("这个
Node 是什么"),这里只负责"这些 Node 怎么串"("外层做组装")——用
Sequence/Loop/ForEach/Checkpoint 直接把 build_xxx_stage() 返回的 Node 对象拼成
一棵树,和下面的结构一一对应:

    setup(Sequence): input_parsing -> concept_expansion -> character_world_design
    outline_loop(Loop, max=4): outline_generation -> outline_critic -> confirm_outline
    chapter_loop(ForEach, 逐章):
        Sequence: chapter_review_loop(Loop, max=4):
                      chapter_drafting -> chapter_critic -> chapter_pause
                  -> chapter_finalize
    sequence: manuscript_assembly_polish -> final_qa

大纲评审(outline_loop)、章节审校(chapter_review_loop)的 body 都是"生成 -> AI
评审 -> 人工确认"三关:AI 判否时 Loop 短路,人工确认根本不会执行;人工反馈同样
驱动下一轮从生成节点重写。两个 Loop 跑满 max_iterations 仍未通过时都升级为人工
断点裁决(on_exceed=escalate_to_checkpoint)——这条流水线设了 Checkpoint,有人在
等着裁决,不像 scenarios/short 那样全自动。

concept_expansion/character_world_design 显式钉住 claude-sonnet-latest(设定的
一致性与创造力最吃这个);其余节点没有标注偏好模型,用哪个由 run.py 的
--model/NOVEL_MODEL 环境变量统一决定,client_for() 对它们一律传 model=None。
"""

from __future__ import annotations

from engine.primitives.foreach import ForEach
from engine.primitives.loop import Loop, OnExceed
from engine.primitives.sequence import Sequence
from engine.workflow import Workflow
from llm.client import LLMClient

from scenarios.novel.nodes.chapter import (
    CHAPTER_LOOP_NAME,
    CHAPTER_REVIEW_LOOP_NAME,
    build_chapter_critic_stage,
    build_chapter_drafting_stage,
    build_chapter_finalize_stage,
    build_chapter_pause_checkpoint,
)
from scenarios.novel.nodes.character_world import build_character_world_design_stage
from scenarios.novel.nodes.common import CHAPTERS_PATH, ClientFactory, needs_revision_continue_when
from scenarios.novel.nodes.concept import build_concept_expansion_stage
from scenarios.novel.nodes.final_qa import build_final_qa_stage
from scenarios.novel.nodes.input_parsing import build_input_parsing_stage
from scenarios.novel.nodes.manuscript import build_manuscript_assembly_polish_stage
from scenarios.novel.nodes.outline import (
    OUTLINE_LOOP_NAME,
    build_confirm_outline_checkpoint,
    build_outline_critic_stage,
    build_outline_generation_stage,
)
from scenarios.novel.state_schema import STORY_BIBLE_SCHEMA

_PINNED_MODEL = "claude-sonnet-latest"


def build_workflow(client_factory: ClientFactory) -> Workflow:
    """组装一个可运行的 novel_generation Workflow。

    Args:
        client_factory: 按 (节点名, model) 取 LLMClient 的工厂函数。
    """

    def client_for(stage_name: str, model: str | None = None) -> LLMClient:
        return client_factory(stage_name, model)

    nodes = [
        Sequence(
            name="setup",
            nodes=[
                build_input_parsing_stage(),
                build_concept_expansion_stage(client_for("concept_expansion", _PINNED_MODEL)),
                build_character_world_design_stage(
                    client_for("character_world_design", _PINNED_MODEL)
                ),
            ],
        ),
        # 一轮 = 生成 + AI 评审 + 人工确认。AI 判否时 continue_when 为真,从
        # outline_generation 重开一轮;上一轮为什么没过,由引擎发布在
        # OUTLINE_LOOP_LAST_PATH 里,outline_generation 用普通的 reads 读它
        # (见 nodes/outline.py)——这条游标和 continue_when 判定谓词是两件独立
        # 的事,判定谓词直接对着 outline_critic/confirm_outline 的 outputs 求值。
        Loop(
            name=OUTLINE_LOOP_NAME,
            continue_when=needs_revision_continue_when,
            max_iterations=4,
            body=[
                build_outline_generation_stage(client_for("outline_generation")),
                build_outline_critic_stage(client_for("outline_critic")),
                build_confirm_outline_checkpoint(),
            ],
            on_exceed=OnExceed.ESCALATE_TO_CHECKPOINT,
        ),
        # 逐章生产:每章先跑一轮"撰写 -> 审校 -> 人工确认"的 Loop,通过后
        # (不论是真通过还是跑满轮次被裁决放行)再跑 chapter_finalize 兜底把
        # status 推进到 "reviewed"。
        ForEach(
            name=CHAPTER_LOOP_NAME,
            items_path=CHAPTERS_PATH,
            body=Sequence(
                name=f"{CHAPTER_LOOP_NAME}_body",
                nodes=[
                    Loop(
                        name=CHAPTER_REVIEW_LOOP_NAME,
                        continue_when=needs_revision_continue_when,
                        max_iterations=4,
                        body=[
                            build_chapter_drafting_stage(client_for("chapter_drafting")),
                            build_chapter_critic_stage(client_for("chapter_critic")),
                            build_chapter_pause_checkpoint(),
                        ],
                        on_exceed=OnExceed.ESCALATE_TO_CHECKPOINT,
                    ),
                    build_chapter_finalize_stage(),
                ],
            ),
        ),
        Sequence(
            name="wrap_up",
            nodes=[
                build_manuscript_assembly_polish_stage(client_for("manuscript_assembly_polish")),
                build_final_qa_stage(),
            ],
        ),
    ]
    return Workflow(name="novel_generation", nodes=nodes, state_schema=STORY_BIBLE_SCHEMA)
