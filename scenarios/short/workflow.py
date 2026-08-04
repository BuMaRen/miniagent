"""在 Python 里直接拼出 short_story_generation 的 Workflow(外层组装)。

不再经过 workflow.yaml/Workflow.from_spec 这层声明式解析:每个 Node 是什么由
scenarios/short/nodes/ 下按业务分组的模块各自负责("这个 Node 是什么"),这里只
负责"这些 Node 怎么串"("外层做组装")——用 Sequence/Loop/ForEach 直接把
build_xxx_stage() 返回的 Stage 对象拼成一棵树,和下面的结构一一对应:

    setup(Sequence): input_parsing -> story_design
    outline_loop(Loop, max=2): outline_generation -> outline_critic
    section_loop(ForEach, 逐节):
        Sequence: section_drafting -> section_review_loop(Loop, max=2):
            section_polish -> section_critic
    final_qa

全程没有 Checkpoint(人工不参与审核),两个 Loop 的 on_exceed 都是
accept_last_version 而不是升级人工裁决——没有人在等着裁决时,escalate 只会把
流程卡死。跑满轮次仍不合格的小节会被放行,但 final_qa 会把它残留的问题写进
qa_report,成品交付时一眼可见哪几节需要人再看一下。

本场景没有任何节点标注偏好的 model——用哪个由 run.py 的 --model / SHORT_MODEL
环境变量统一决定,所以 client_for() 一律传 model=None。
"""

from __future__ import annotations

from engine.primitives.foreach import ForEach
from engine.primitives.loop import Loop, OnExceed
from engine.primitives.sequence import Sequence
from engine.workflow import Workflow
from llm.client import LLMClient

from scenarios.short.nodes.common import ClientFactory, NEEDS_REVISION_KEY, SECTIONS_PATH
from scenarios.short.nodes.final_qa import build_final_qa_stage
from scenarios.short.nodes.input_parsing import build_input_parsing_stage
from scenarios.short.nodes.outline import (
    OUTLINE_LOOP_LAST_PATH,
    OUTLINE_LOOP_NAME,
    build_outline_critic_stage,
    build_outline_generation_stage,
)
from scenarios.short.nodes.section import (
    SECTION_LOOP_NAME,
    SECTION_REVIEW_LOOP_LAST_PATH,
    SECTION_REVIEW_LOOP_NAME,
    build_section_critic_stage,
    build_section_drafting_stage,
    build_section_polish_stage,
)
from scenarios.short.nodes.story_design import build_story_design_stage
from scenarios.short.state_schema import SHORT_STORY_SCHEMA


def build_workflow(client_factory: ClientFactory) -> Workflow:
    """组装一个可运行的 short_story_generation Workflow。

    Args:
        client_factory: 按 (节点名, model) 取 LLMClient 的工厂函数;本场景一律传
            model=None(见模块 docstring)。
    """

    def client_for(stage_name: str) -> LLMClient:
        return client_factory(stage_name, None)

    nodes = [
        Sequence(
            name="setup",
            nodes=[
                build_input_parsing_stage(),
                build_story_design_stage(client_for("story_design")),
            ],
        ),
        # 大纲一轮 = 生成 + 评审。评审判否时 continue_when 为真,从
        # outline_generation 重开一轮;上一轮为什么没过,由引擎发布在
        # OUTLINE_LOOP_LAST_PATH 里,outline_generation 用普通的 reads 读它。
        # 只留 2 轮:大纲返工比正文返工便宜,但也就值一次重来——剧情与爆点的骨架
        # 在这里定死,后面不再有全局性的返工机会。
        Loop(
            name=OUTLINE_LOOP_NAME,
            continue_when=f"{OUTLINE_LOOP_LAST_PATH}.{NEEDS_REVISION_KEY}",
            max_iterations=2,
            body=[
                build_outline_generation_stage(client_for("outline_generation")),
                build_outline_critic_stage(client_for("outline_critic")),
            ],
            on_exceed=OnExceed.ACCEPT_LAST,
        ),
        # 逐节生产:Sequence 先保底跑一次撰写(管情节与爽点,只跑这一次、不进
        # 循环——情节与爽点定死之后不再重赌),再进 section_review_loop 反复
        # "精修(只管语言)-> 审校"直到过关或跑满轮次。
        #
        # body 顺序是 [section_polish, section_critic] 而不是反过来:Loop 的
        # 短路只在 continue_when 为真时跳过本轮剩下的节点,判否时从
        # body[0]=section_polish 重开一轮;若审校放在前面,判过之后 body 还会
        # 不短路地继续往下跑,白白多跑一次精修。
        #
        # 审校发现的问题(含字数下限——硬要求)一票否决,不管模型自己怎么判;
        # 精修下一轮会读到具体的驳回理由(见 SECTION_REVIEW_LOOP_LAST_PATH)。
        # 只留 2 轮:正文的返工只改语言不改情节,代价可控,但也不该无限期跑下去。
        ForEach(
            name=SECTION_LOOP_NAME,
            items_path=SECTIONS_PATH,
            body=Sequence(
                name=f"{SECTION_LOOP_NAME}_body",
                nodes=[
                    build_section_drafting_stage(client_for("section_drafting")),
                    Loop(
                        name=SECTION_REVIEW_LOOP_NAME,
                        continue_when=f"{SECTION_REVIEW_LOOP_LAST_PATH}.{NEEDS_REVISION_KEY}",
                        max_iterations=2,
                        body=[
                            build_section_polish_stage(client_for("section_polish")),
                            build_section_critic_stage(client_for("section_critic")),
                        ],
                        on_exceed=OnExceed.ACCEPT_LAST,
                    ),
                ],
            ),
        ),
        # 终检(纯函数):补全字数统计,产出 qa_report。
        build_final_qa_stage(),
    ]
    return Workflow(name="short_story_generation", nodes=nodes, state_schema=SHORT_STORY_SCHEMA)
