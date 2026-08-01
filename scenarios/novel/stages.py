"""本场景的节点:能声明的都在 stages.yaml 里,这里只留必须用 Python 表达的部分。

节点的装配(建 Agent、挂 ToolSet、塞提示词、传 output_schema、包成 Stage)已经
下沉到框架(engine/spec.py),场景侧因此只剩三类东西:

1. **纯函数 executor** —— input_parsing(默认值填充)、chapter_finalize(状态推进)、
   final_qa(字数/结构核对)都是确定性计算,用普通函数当 executor 比用 LLM 更可靠
   也更省成本;它们用 `@executor` 装饰器登记,stages.yaml 里按名引用。这正是
   docs/framework-design.md §3.2 强调的"Stage 不关心怎么产出输出"的体现。
2. **带副作用的节点包装** —— 章节 status 的推进(reviewed / 打回 drafted)是评审
   节点的旁路写回:这两个节点自己的输出契约是 {needs_revision, feedback},容不下
   额外的 story_bible.chapters 字段,只能以 Node 协议允许的"直接读写 ctx.state"
   完成。声明式定义表达不了这种副作用,所以先让框架按 stages.yaml 建出节点,再在
   外面包一层薄薄的 Node(见 _with_status_writeback / _ChapterHumanReviewCheckpoint)。
3. **build_node_registry** —— 把提示词/schema/工具集三个目录登记进各自的注册表,
   调框架的 build_node_registry,再打上那两层包装。

提示词全部在 prompts/*.prompt 里(风格基调 style_guide 被 7 段提示词各引用一次,
不再像以前那样靠 f-string 拼);各 Stage 的 output_schema 在 schemas/*.yaml 里,
需要复用 story_bible 子结构(character/chapter/...)的靠 types=NOVEL_TYPES 从
state_schema.yaml 借出那张具名类型表。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import prompts
from agent import toolset as toolset_registry
from engine.context import RunContext
from engine.spec import ClientFactory, build_node_registry as build_node_registry_from_spec
from engine.stage import Node, executor
from engine.workflow import NodeRegistry
from state import schema as schema_registry

from scenarios.novel.state_schema import NOVEL_TYPES, STORY_BIBLE_SCHEMA
from scenarios.novel.toolsets.qa import QA_TOOLSET, count_chinese_characters
from scenarios.novel.toolsets.research import RESEARCH_TOOLSET

_HERE = Path(__file__).parent
STAGES_YAML_PATH = _HERE / "stages.yaml"
PROMPTS_DIR = _HERE / "prompts"
SCHEMAS_DIR = _HERE / "schemas"

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


# ---------------------------------------------------------------------------
# 三、组装:登记三张注册表 -> 交给框架按 stages.yaml 建节点 -> 打上两层包装
# ---------------------------------------------------------------------------


def build_node_registry(
    client_factory: ClientFactory, stage_models: dict[str, str] | None = None
) -> NodeRegistry:
    """按 stages.yaml 组装本场景全部节点,注册进一个新的 NodeRegistry。

    Args:
        client_factory: 按 (节点名, model) 取一个 LLMClient 的工厂函数。真实运行
            通常按 model 分组复用 client 实例;线下演示按名字返回预置好回复的
            ScriptedLLMClient(见 offline_demo.py),忽略 model。
        stage_models: workflow.yaml 里每个节点名解析出的生效 model(见
            engine.workflow.Workflow.resolve_stage_models);某个节点及其所有祖先
            节点都没标注过 model 时不出现在这个 dict 里,此时传给 client_factory
            的 model 为 None。

    注册表都是全局的(每个模块的 default_registry),登记又是幂等的,所以这里每次
    都无脑登记一遍:重复调用(测试里很常见)不会互相干扰。
    """
    prompts.load_dir(PROMPTS_DIR)
    schema_registry.default_registry.load_dir(SCHEMAS_DIR, types=NOVEL_TYPES)
    schema_registry.default_registry.register(STORY_BIBLE_SCHEMA)
    toolset_registry.register(RESEARCH_TOOLSET)
    toolset_registry.register(QA_TOOLSET)

    registry = build_node_registry_from_spec(
        STAGES_YAML_PATH,
        client_factory=client_factory,
        stage_models=stage_models,
    )
    registry.replace(_ChapterCriticWithStatusWriteback(registry.get("chapter_critic")))
    registry.replace(_ChapterHumanReviewCheckpoint(registry.get("chapter_pause")))
    return registry


__all__ = [
    "STORY_BIBLE_SCHEMA",
    "ClientFactory",
    "CHAPTER_LOOP_ITEM_PATH",
    "CHAPTER_REVIEW_LOOP_LAST_PATH",
    "NEEDS_REVISION_KEY",
    "OUTLINE_LOOP_LAST_PATH",
    "build_node_registry",
]
