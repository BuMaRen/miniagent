"""本场景在声明式定义(stages.yaml/state_schema.yaml/schemas//prompts//toolsets/)
之外,真正需要手写 Python 的那一小部分——按 engine/scenario.py 的目录约定,本文件在
`Scenario.from_package` 装配场景时被自动 import 一次,用来触发下面两类装饰器的登记
副作用;其余装配(读 YAML、登记四张注册表、拼 Workflow)都已经下沉到框架。

1. **纯函数 executor** —— input_parsing(默认值填充)、chapter_finalize(状态推进)、
   final_qa(字数/结构核对)都是确定性计算,用普通函数当 executor 比用 LLM 更可靠
   也更省成本;它们用 `@executor` 装饰器登记,stages.yaml 里按名引用。这正是
   docs/framework-design.md §3.2 强调的"Stage 不关心怎么产出输出"的体现。
2. **节点包装工厂** —— 章节 status 的推进(reviewed / 打回 drafted)是评审节点的
   旁路写回:这两个节点自己的输出契约是 {needs_revision, feedback},容不下额外的
   story_bible.chapters 字段,只能以 Node 协议允许的"直接读写 ctx.state"完成。
   声明式定义表达不了这种副作用,所以用 `@node_wrapper` 登记一个 (Node) -> Node
   的包装函数,再在 stages.yaml 对应节点上写 `wrap: 包装器名` 引用它(见
   engine/spec.py 的 NodeBuilder)。
"""

from __future__ import annotations

from typing import Any

from engine.context import RunContext
from engine.stage import Node, executor, node_wrapper
from scenarios.novel.toolsets.qa import count_chinese_characters

# Loop 的游标:引擎把"上一个跑完的 body 节点的产出"整块发布在这条状态路径上
# (见 engine/primitives/loop.py),形如 f"_loop.{loop 的 name}.last"。它是"上一轮
# 为什么没过"的唯一通道 —— 本轮第一个节点用普通的 reads 读它(见 stages.yaml),
# 而不是靠 Loop 把 feedback 塞进 inputs。这里的名字必须和 workflow.yaml 里各
# loop 的 name 对得上;stages.yaml 与提示词里出现的也是同一批字面量。
OUTLINE_LOOP_LAST_PATH = "_loop.outline_loop.last"
CHAPTER_REVIEW_LOOP_LAST_PATH = "_loop.chapter_review_loop.last"
CHAPTER_LOOP_ITEM_PATH = "_foreach.chapter_loop.item"

# 评审类节点(AI critic 与人工 Checkpoint)约定输出的判定字段名。极性刻意朝着
# "还要再改一轮"为真:workflow.yaml 里的 continue_when 是一条裸状态路径、引擎只
# 取它的真假,没有取反的余地(取反就得引入表达式语言,见 loop.py 的说明)。
NEEDS_REVISION_KEY = "needs_revision"

_DEFAULT_TARGET_WORD_COUNT = [8000, 20000]


# ---------------------------------------------------------------------------
# 一、纯函数 executor(stages.yaml 里按函数名引用)
# ---------------------------------------------------------------------------


@executor
def input_parsing_executor(ctx: RunContext, inputs: dict[str, Any]) -> dict[str, Any]:
    """校验/补全用户输入,产出故事圣经 meta 的初始骨架。"""
    topic = inputs.get("topic")
    if not topic:
        raise ValueError("input_parsing: 缺少必填字段 'topic'")

    meta = {
        "title": "",
        "logline": "",
        "theme": "",
        "core_conflict": "",
        "structure_template": inputs.get("structure_template") or "三幕式",
        "target_word_count": inputs.get("target_word_count") or _DEFAULT_TARGET_WORD_COUNT,
        "genre": inputs.get("genre") or "历史·现实主义",
        "pov": inputs.get("pov") or "第一人称",
        "tone": inputs.get("tone") or "沉稳克制,重考据与心理真实,非爽文",
    }
    return {"story_bible.meta": meta, "topic": topic}


@executor
def chapter_finalize_executor(ctx: RunContext, inputs: dict[str, Any]) -> dict[str, Any]:
    """兜底把本章 status 推进到 "reviewed"。

    正常路径下 chapter_critic 一过审就已经乐观地写成 "reviewed"(见
    _with_status_writeback 的说明),这里再写一遍是幂等的;真正依赖这一步的是
    chapter_review_loop 跑满 max_iterations、按 on_exceed=escalate_to_checkpoint
    升级为人工裁决的路径——那条路径不经过 chapter_critic 的最终通过判定,该章此时
    仍停在 "drafted",要靠这里推一把才能继续往下一章走。它走的是哪条路径可以从
    inputs["_loop"]["exhausted"] 看出来(Loop 的返回值),两条路径都该定稿,
    所以这里不必分支。
    """
    current_index = (inputs.get("state", {}).get(CHAPTER_LOOP_ITEM_PATH) or {}).get("index")
    _set_chapter_status(ctx, current_index, "reviewed")
    return {}


@executor
def final_qa_executor(ctx: RunContext, inputs: dict[str, Any]) -> dict[str, Any]:
    """校验总字数/章节完整性,补全字数统计,产出呈现用的元数据。"""
    state = inputs.get("state", {})
    chapters = state.get("story_bible.chapters") or []
    meta = dict(state.get("story_bible.meta") or {})

    updated_chapters = []
    total_words = 0
    for chapter in chapters:
        text = chapter.get("text", "")
        word_count = count_chinese_characters(text)
        total_words += word_count
        updated_chapters.append({**chapter, "word_count": word_count})

    min_count, max_count = (meta.get("target_word_count") or [0, 0])[:2] or (0, 0)
    qa_report = {
        "total_word_count": total_words,
        "chapter_count": len(chapters),
        "all_chapters_have_text": all(c.get("text") for c in chapters),
        "in_target_range": (min_count <= total_words <= max_count) if max_count else None,
        "has_title": bool(meta.get("title")),
    }

    return {
        "story_bible.chapters": updated_chapters,
        "qa_report": qa_report,
        "title": meta.get("title", ""),
        "logline": meta.get("logline", ""),
    }


# ---------------------------------------------------------------------------
# 二、章节 status 的旁路写回:声明式定义表达不了的那点副作用
# ---------------------------------------------------------------------------


def _set_chapter_status(ctx: RunContext, chapter_index: Any, status: str) -> None:
    """把 story_bible.chapters 中下标为 chapter_index 的那一条 status 改写为 status。

    直接经 ctx.state 读写,不走 Stage 的声明式 writes——调用方(chapter_critic /
    chapter_pause)本身的输出契约是评审的 {needs_revision, feedback},容不下额外的
    story_bible.chapters 字段。
    """
    chapters = ctx.state.get("story_bible.chapters", default=[]) or []
    updated_chapters = [
        {**chapter, "status": status} if chapter.get("index") == chapter_index else chapter
        for chapter in chapters
    ]
    ctx.state.patch("story_bible.chapters", updated_chapters)


class _ChapterCriticWithStatusWriteback:
    """包一层 chapter_critic:AI 一过审就乐观地把该章 status 推进到 "reviewed"。

    为什么不等 chapter_pause 也点头之后才推进——chapter_pause 若选择"暂停保存进度"
    (见 run.py 的 CheckpointPause 分支),ForEach 会在暂停前先把游标 advance 到
    下一章(engine/primitives/foreach.py 的 except 分支),导致这一章再也不会被重新
    访问、chapter_finalize 也不会再跑到它。乐观地先标 "reviewed" 保证了"卡在断点"
    不等于"永远卡在 drafted";人工真的给出不通过意见时,由 chapter_pause 自己把它
    打回 "drafted"(见 _ChapterHumanReviewCheckpoint)。
    """

    def __init__(self, node: Node) -> None:
        self._node = node
        self.name = node.name

    def run(self, ctx: RunContext, inputs: dict[str, Any]) -> dict[str, Any]:
        verdict = self._node.run(ctx, inputs)
        if not verdict.get(NEEDS_REVISION_KEY):
            _set_chapter_status(ctx, inputs.get("chapter_index"), "reviewed")
        return verdict


class _ChapterHumanReviewCheckpoint:
    """包一层 chapter_pause:人工给出"不通过"时把该章 status 从上面乐观写入的
    "reviewed" 打回 "drafted",驱动 chapter_review_loop 下一轮重新修订;通过、或
    尚未决定就暂停(见 run.py 的 "q" 分支)时都保留 "reviewed"——"暂停"不代表
    "不通过",不该把还没被人工否决的章节退回 drafted。

    仍然是名副其实的 Node(name + run),可以像原生 Checkpoint 一样放进 Loop 的
    body;暂停/恢复的机制(ctx.resume 认领、CheckpointPause)完全委托给内部持有的
    那个真正的 engine Checkpoint,这里只在其返回之后补一刀状态写回,不侵入引擎的
    暂停语义。
    """

    def __init__(self, node: Node) -> None:
        self._node = node
        self.name = node.name

    def run(self, ctx: RunContext, inputs: dict[str, Any]) -> dict[str, Any]:
        result = self._node.run(ctx, inputs)
        if result.get(NEEDS_REVISION_KEY):
            _set_chapter_status(ctx, result.get("chapter_index"), "drafted")
        return result


@node_wrapper
def chapter_critic_status_writeback(node: Node) -> Node:
    return _ChapterCriticWithStatusWriteback(node)


@node_wrapper
def chapter_human_review_writeback(node: Node) -> Node:
    return _ChapterHumanReviewCheckpoint(node)


__all__ = [
    "CHAPTER_LOOP_ITEM_PATH",
    "CHAPTER_REVIEW_LOOP_LAST_PATH",
    "NEEDS_REVISION_KEY",
    "OUTLINE_LOOP_LAST_PATH",
]
