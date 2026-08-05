"""逐章撰写、审校与定稿(3.6-3.8)—— chapter_loop(ForEach)与
chapter_review_loop(Loop)的 body。

chapter_critic 与 chapter_pause 都在自己的评审契约({needs_revision, feedback})
之外,还要顺带把 story_bible.chapters 里对应那一章的 status 往前推进/打回——
这点声明式的 reads/writes 表达不了(两个节点的输出契约容不下额外的
story_bible.chapters 字段),所以直接经 ctx.state 读写,用一个满足 Node 协议的
薄包装类套在原节点外面(见 docs/framework-design.md §6.5 "场景自定义节点")。
"""

from __future__ import annotations

from typing import Any

from engine.context import RunContext
from engine.primitives.checkpoint import Checkpoint
from engine.primitives.foreach import foreach_item_path
from engine.primitives.loop import loop_cursor_path
from engine.stage import Node, Stage
from llm.client import LLMClient
from state.schema import StateSchema

from scenarios.novel import prompts
from scenarios.novel.nodes.common import (
    CHAPTERS_PATH,
    CHARACTERS_PATH,
    CRITIC_OUTPUT_SCHEMA,
    FORESHADOWING_PATH,
    META_PATH,
    NEEDS_REVISION_KEY,
    TIMELINE_PATH,
    WORLD_PATH,
    make_agent,
)
from scenarios.novel.state_schema import CHAPTER
from scenarios.novel.toolsets.qa import QA_TOOLSET
from scenarios.novel.toolsets.research import RESEARCH_TOOLSET

CHAPTER_LOOP_NAME = "chapter_loop"
CHAPTER_LOOP_ITEM_PATH = foreach_item_path(CHAPTER_LOOP_NAME)

CHAPTER_REVIEW_LOOP_NAME = "chapter_review_loop"
CHAPTER_REVIEW_LOOP_LAST_PATH = loop_cursor_path(CHAPTER_REVIEW_LOOP_NAME)

CHAPTER_DRAFTING_OUTPUT_SCHEMA = StateSchema(
    "chapter_drafting_output",
    {CHAPTERS_PATH: [CHAPTER], "chapter_index": int, "chapter_text": str},
)


def build_chapter_drafting_stage(client: LLMClient) -> Stage:
    agent = make_agent(
        client,
        prompts.CHAPTER_DRAFTING,
        toolsets=(RESEARCH_TOOLSET,),
        output_schema=CHAPTER_DRAFTING_OUTPUT_SCHEMA,
    )
    return Stage(
        name="chapter_drafting",
        executor=agent.run,
        reads=[
            CHAPTER_REVIEW_LOOP_LAST_PATH,
            CHAPTER_LOOP_ITEM_PATH,
            META_PATH,
            CHARACTERS_PATH,
            WORLD_PATH,
            FORESHADOWING_PATH,
            CHAPTERS_PATH,
        ],
        writes=[CHAPTERS_PATH],
        output_schema=CHAPTER_DRAFTING_OUTPUT_SCHEMA,
    )


# ---------------------------------------------------------------------------
# 章节 status 的旁路写回
# ---------------------------------------------------------------------------


def _set_chapter_status(ctx: RunContext, chapter_index: Any, status: str) -> None:
    """把 story_bible.chapters 中下标为 chapter_index 的那一条 status 改写为 status。"""
    chapters = ctx.state.get(CHAPTERS_PATH, default=[]) or []
    updated_chapters = [
        {**chapter, "status": status} if chapter.get("index") == chapter_index else chapter
        for chapter in chapters
    ]
    ctx.state.patch(CHAPTERS_PATH, updated_chapters)


def _current_chapter_index(ctx: RunContext) -> Any:
    """当前 chapter_loop 迭代到的章节下标,由 ForEach 发布在游标里(见
    engine/primitives/foreach.py)。两个包装类都靠它定位要改写的那一章,而不是
    依赖上游节点 outputs 里的 chapter_index 字段——chapter_critic 的输出契约是
    严格的 {needs_revision, feedback}(走 Provider 结构化输出,不接受额外字段),
    chapter_index 这类字段传不过 chapter_critic 这一关,到 chapter_pause 时已经
    丢了。
    """
    return (ctx.state.get(CHAPTER_LOOP_ITEM_PATH) or {}).get("index")


class _ChapterCriticWithStatusWriteback:
    """包一层 chapter_critic:AI 一过审就乐观地把该章 status 推进到 "reviewed"。

    不等 chapter_pause 也点头之后才推进,是为了让"AI 已认可、人工尚未表态"这个
    中间状态也能被外部看到是"reviewed"而不是"drafted"——人工真的给出不通过意见时,
    由 chapter_pause 自己把它打回 "drafted"(见 _ChapterHumanReviewCheckpoint)。
    """

    def __init__(self, node: Node) -> None:
        self._node = node
        self.name = node.name

    def run(self, ctx: RunContext, inputs: dict[str, Any]) -> dict[str, Any]:
        verdict = self._node.run(ctx, inputs)
        if not verdict.get(NEEDS_REVISION_KEY):
            _set_chapter_status(ctx, _current_chapter_index(ctx), "reviewed")
        return verdict


class _ChapterHumanReviewCheckpoint:
    """包一层 chapter_pause:人工给出"不通过"时把该章 status 从上面乐观写入的
    "reviewed" 打回 "drafted",驱动 chapter_review_loop 下一轮重新修订;通过、或
    尚未决定就退出(见 run.py 里 Checkpoint handler 的"暂停"分支,直接抛异常触发
    WorkflowFailure)时都保留 "reviewed"——中途退出不代表"不通过",不该把还没被
    人工否决的章节退回 drafted。

    仍然是名副其实的 Node(name + run),可以像原生 Checkpoint 一样放进 Loop 的
    body;向外部要输入这件事完全委托给内部持有的那个真正的 engine Checkpoint,
    这里只在其返回之后补一刀状态写回。
    """

    def __init__(self, node: Node) -> None:
        self._node = node
        self.name = node.name

    def run(self, ctx: RunContext, inputs: dict[str, Any]) -> dict[str, Any]:
        result = self._node.run(ctx, inputs)
        if result.get(NEEDS_REVISION_KEY):
            _set_chapter_status(ctx, _current_chapter_index(ctx), "drafted")
        return result


def build_chapter_critic_stage(client: LLMClient) -> Node:
    agent = make_agent(
        client, prompts.CHAPTER_CRITIC, toolsets=(QA_TOOLSET,), output_schema=CRITIC_OUTPUT_SCHEMA
    )
    stage = Stage(
        name="chapter_critic",
        executor=agent.run,
        reads=[CHARACTERS_PATH, WORLD_PATH, TIMELINE_PATH, FORESHADOWING_PATH],
        output_schema=CRITIC_OUTPUT_SCHEMA,
    )
    return _ChapterCriticWithStatusWriteback(stage)


def build_chapter_pause_checkpoint() -> Node:
    checkpoint = Checkpoint(
        name="chapter_pause",
        prompt="本章已通过 AI 审校,请确认是否继续下一章;不通过请给出修改意见。",
        resume_input_schema=CRITIC_OUTPUT_SCHEMA,
    )
    return _ChapterHumanReviewCheckpoint(checkpoint)


# ---------------------------------------------------------------------------
# 章节定稿:兜底把 status 推进到 "reviewed",纯函数
# ---------------------------------------------------------------------------


def chapter_finalize_executor(ctx: RunContext, inputs: dict[str, Any]) -> dict[str, Any]:
    """兜底把本章 status 推进到 "reviewed"。

    正常路径下 chapter_critic 一过审就已经乐观地写成 "reviewed"(见
    _ChapterCriticWithStatusWriteback 的说明),这里再写一遍是幂等的;真正依赖
    这一步的是 chapter_review_loop 跑满 max_iterations、按
    on_exceed=escalate_to_checkpoint 升级为人工裁决的路径——那条路径不经过
    chapter_critic 的最终通过判定,该章此时仍停在 "drafted",要靠这里推一把才能
    继续往下一章走。它走的是哪条路径可以从 inputs["_loop"]["exhausted"] 看出来
    (Loop 的返回值),两条路径都该定稿,所以这里不必分支。
    """
    current_index = (inputs.get("state", {}).get(CHAPTER_LOOP_ITEM_PATH) or {}).get("index")
    _set_chapter_status(ctx, current_index, "reviewed")
    return {}


def build_chapter_finalize_stage() -> Stage:
    return Stage(
        name="chapter_finalize",
        executor=chapter_finalize_executor,
        reads=[CHAPTER_LOOP_ITEM_PATH],
    )
