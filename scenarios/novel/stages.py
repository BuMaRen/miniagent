"""把 ToolSet 挂到 Agent 上,组装成本场景需要的各个节点(docs/framework-design.md §8 步骤 2-3)。

对应 docs/workflow-design.md §4 的表格:每一行是一个 Stage,这里逐一实现。刻意
不是每个 Stage 都用 Agent 执行——input_parsing(默认值填充)和 final_qa(字数/
结构核对)是纯粹的确定性计算,用普通函数当 executor 更可靠也更省成本;这正是
docs/framework-design.md §3.2 强调的"Stage 不关心怎么产出输出"的体现。

本模块产出的也不全是 Stage:人工复核点是 Checkpoint(引擎原语),两条评审链是
ReviewChain(本场景自定义的 Node,见 review_chain.py)。它们和 Stage 一起被登记
进同一张 NodeRegistry、在 workflow.yaml 里以同样的方式按名引用——因为引擎要求的
从来只是 Node 协议,而不是 Stage 这个具体类型。

风格基调统一交给 _STYLE_GUIDE:现代人穿越西汉、随张骞出使西域这个题材最容易
写成"金手指爽文",这里明确要求现实主义——身体的脆弱、制度的压迫感、信息不
对称都要保留,人物会犯错、会害怕。
"""

from __future__ import annotations

from typing import Any, Callable

from agent.agent import Agent
from agent.memory import ConversationMemory
from engine.context import RunContext
from engine.primitives.checkpoint import Checkpoint
from scenarios.novel.review_chain import ReviewChain
from engine.stage import Node, Stage
from llm.client import LLMClient
from state.schema import StateSchema
from tools.registry import ToolRegistry

from scenarios.novel.state_schema import CHAPTER, CHARACTER, FORESHADOWING, STORY_BIBLE_SCHEMA, WORLD_ENTRY
from scenarios.novel.toolsets.research import RESEARCH_TOOLSET
from scenarios.novel.toolsets.qa import QA_TOOLSET, count_chinese_characters

# 由调用方(run.py / offline_demo.py)提供:按 Stage 名给出一个 LLMClient。
# 真实运行通常对所有 Stage 返回同一个 client 实例;线下演示按 Stage 返回预先
# 编排好回复的 ScriptedLLMClient,便于在没有真实 API Key 时验证整条流水线。
ClientFactory = Callable[[str], LLMClient]

_DEFAULT_MAX_STEPS = 8

_STYLE_GUIDE = """
【题材设定】现代人意外跌落进西汉汉武帝建元年间的长安,起初只是想活下去、
弄清楚自己为何/如何来到这里,后来机缘之下随张骞出使西域。

【风格要求 —— 现实主义,不是爽文】
- 主角没有"金手指":不会武功、不能未卜先知具体明天会发生什么,"知道历史大势"
  换不来眼前的一顿饭、一张路引、一句得体的问候。
- 保留身体的脆弱(饥饿、寒冷、伤病)与制度的压迫感(路引、乡里连坐、宵禁、
  官府盘查),这些具体的麻烦比"扮演穿越者"更值得写。
- 人物会犯错、会害怕、会被现实教训,不要写成无所不能或永远正确。
- 语言克制、具体、有感官细节,避免空洞形容词堆砌与"AI 味"套话(排比抒情、
  反复的"仿佛""不禁""究竟"式转折)。
- 叙述人称以 story_bible.meta.pov 的设定为准(未指定则默认第一人称)。若 pov
  要求第三人称,通篇用 story_bible.characters 里 role 为 "protagonist" 的那个
  人物的 name 指代主角,禁止出现第一人称代词"我";其余仍保持现在/回忆交织的
  克制叙述语气。
- 涉及制度、器物、纪年、货币等细节,如有疑问请先用 lookup_han_dynasty_fact
  查证,不要凭现代常识臆测(例如:此时还没有"五铢钱""年号"式的日常自称)。
"""

_JSON_ONLY = (
    "只输出一个 JSON 对象作为最终回复,不要包含任何 JSON 之外的说明文字、"
    "不要用 Markdown 代码块包裹。JSON 的顶层键名必须与下面列出的完全一致"
    "(包括其中的点号),不要嵌套在别的键下面。"
)


def _make_agent(
    client: LLMClient,
    system_prompt: str,
    toolsets: tuple = (),
    output_schema: StateSchema | None = None,
) -> Agent:
    registry = ToolRegistry()
    agent = Agent(
        client=client,
        memory=ConversationMemory(system_prompt=system_prompt),
        registry=registry,
        max_steps=_DEFAULT_MAX_STEPS,
        output_schema=output_schema,
    )
    for toolset in toolsets:
        agent.load_toolset(toolset)
    return agent


# ---------------------------------------------------------------------------
# 3.1 输入解析 —— 纯函数 executor,不需要 LLM。
# ---------------------------------------------------------------------------

_DEFAULT_TARGET_WORD_COUNT = [8000, 20000]


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


def build_input_parsing_stage() -> Stage:
    return Stage(name="input_parsing", executor=input_parsing_executor, writes=["story_bible.meta"])


# ---------------------------------------------------------------------------
# 3.2 立意扩展
# ---------------------------------------------------------------------------

_CONCEPT_PROMPT = f"""你负责小说创作流程中的"立意扩展"阶段。
{_STYLE_GUIDE}
输入会包含题材(topic)以及当前的 story_bible.meta(可能 title/logline 等尚为空)。
你的任务:把题材扩展为 logline(一句话故事)、theme(这篇小说想说什么)、
core_conflict(核心冲突:谁 vs 谁/什么,为什么无法回避)。这一步不产出情节细节,
只锁定"为什么值得写"与"冲突是什么",作为后续大纲的锚点。

{_JSON_ONLY}
输出格式:
{{"story_bible.meta": {{"logline": "...", "theme": "...", "core_conflict": "..."}}}}
"""


CONCEPT_EXPANSION_OUTPUT_SCHEMA = StateSchema(
    "concept_expansion_output",
    {"story_bible.meta": {"logline": str, "theme": str, "core_conflict": str}},
)


def build_concept_expansion_stage(client: LLMClient) -> Stage:
    agent = _make_agent(
        client,
        _CONCEPT_PROMPT,
        toolsets=(RESEARCH_TOOLSET,),
        output_schema=CONCEPT_EXPANSION_OUTPUT_SCHEMA,
    )
    return Stage(
        name="concept_expansion",
        executor=agent.run,
        reads=["story_bible.meta"],
        writes=["story_bible.meta"],
        output_schema=CONCEPT_EXPANSION_OUTPUT_SCHEMA,
    )


# ---------------------------------------------------------------------------
# 3.3 角色与世界观设计
# ---------------------------------------------------------------------------

_CHARACTER_WORLD_PROMPT = f"""你负责小说创作流程中的"角色与世界观设计"阶段。
{_STYLE_GUIDE}
输入包含 story_bible.meta(已有 logline/theme/core_conflict)。
你的任务:
1. 起一个正式标题(写入 story_bible.meta.title,可以化用"凿空"这类与张骞出使
   西域相关的史实意象,但不强制)。
2. 设计主角、以及推动/阻碍主角的关键配角(2-4 人足够,不要贪多);每个角色要
   有 id/name/role(protagonist|antagonist|supporting)/goal/motivation/flaw/arc,
   antagonist 可以是"具体的人",也可以是制度性的压力(如基层官吏代表的猜疑
   与盘查)——现实主义故事不强求脸谱化反派。
3. 补充最小必要的世界观规则(只写情节会用到的规则,如路引制度、市集与宵禁、
   张骞出使西域的历史背景),每条要标注 established_in_chapter(通常是 1)。
这一阶段还没有章节可记录,每个角色的 status_log 留空数组即可;后续阶段若要
往里追加,元素形状必须是 {{"after_chapter": 1, "state": "..."}}。

{_JSON_ONLY}
输出格式:
{{
  "story_bible.meta": {{"title": "..."}},
  "story_bible.characters": [{{"id": "...", "name": "...", "role": "...",
    "goal": "...", "motivation": "...", "flaw": "...", "arc": "...",
    "relationships": [{{"target_id": "另一个角色的 id", "relation": "..."}}], "status_log": []}}],
  "story_bible.world": [{{"id": "...", "name": "...", "description": "...",
    "established_in_chapter": 1}}]
}}
"""


CHARACTER_WORLD_DESIGN_OUTPUT_SCHEMA = StateSchema(
    "character_world_design_output",
    {
        "story_bible.meta": {"title": str},
        "story_bible.characters": [CHARACTER],
        "story_bible.world": [WORLD_ENTRY],
    },
)


def build_character_world_design_stage(client: LLMClient) -> Stage:
    agent = _make_agent(
        client,
        _CHARACTER_WORLD_PROMPT,
        toolsets=(RESEARCH_TOOLSET,),
        output_schema=CHARACTER_WORLD_DESIGN_OUTPUT_SCHEMA,
    )
    return Stage(
        name="character_world_design",
        executor=agent.run,
        reads=["story_bible.meta"],
        writes=["story_bible.meta", "story_bible.characters", "story_bible.world"],
        output_schema=CHARACTER_WORLD_DESIGN_OUTPUT_SCHEMA,
    )


# ---------------------------------------------------------------------------
# 3.4 / 3.5 大纲生成与大纲评审(Loop 的 producer/reviser 与 critic)
# ---------------------------------------------------------------------------

_OUTLINE_PROMPT = f"""你负责小说创作流程中的"大纲与节拍生成"阶段。
{_STYLE_GUIDE}
输入包含 story_bible.meta、story_bible.characters、story_bible.world。
如果 inputs 里还带着 feedback 字段,说明这是一次修订:请针对 feedback
指出的问题修改大纲,而不是推倒重写。

你的任务:按 meta.structure_template 生成章节列表,中短篇建议 6-15 章,
单章 1000-2500 字;每章包含 index/title/beat_summary(该章目标、关键事件、
结尾钩子、涉及的角色与伏笔)。同时规划伏笔(foreshadowing):哪一章埋下、
计划哪一章回收——payoff_chapter 请直接填入计划回收的具体章节号,不要留
null,"计划哪一章回收"这个决定就应该在这一步做出,不要留给后续阶段猜。

{_JSON_ONLY}
输出格式:
{{
  "story_bible.chapters": [{{"index": 1, "title": "...", "beat_summary": "...",
    "draft_summary": "", "text": "", "word_count": 0, "status": "planned"}}],
  "story_bible.foreshadowing": [{{"id": "...", "planted_in_chapter": 1,
    "description": "...", "payoff_chapter": 5, "status": "planted"}}]
}}
"""


OUTLINE_GENERATION_OUTPUT_SCHEMA = StateSchema(
    "outline_generation_output",
    {"story_bible.chapters": [CHAPTER], "story_bible.foreshadowing": [FORESHADOWING]},
)


def build_outline_generation_stage(client: LLMClient) -> Stage:
    agent = _make_agent(
        client,
        _OUTLINE_PROMPT,
        toolsets=(RESEARCH_TOOLSET,),
        output_schema=OUTLINE_GENERATION_OUTPUT_SCHEMA,
    )
    return Stage(
        name="outline_generation",
        executor=agent.run,
        reads=["story_bible.meta", "story_bible.characters", "story_bible.world"],
        writes=["story_bible.chapters", "story_bible.foreshadowing"],
        output_schema=OUTLINE_GENERATION_OUTPUT_SCHEMA,
    )


_OUTLINE_CRITIC_PROMPT = f"""你负责小说创作流程中的"大纲评审"阶段,是 Critic,不负责改写。
{_STYLE_GUIDE}
输入包含刚生成的 story_bible.chapters / story_bible.foreshadowing,以及
story_bible.meta / story_bible.characters 供你核对呼应关系。

评审维度:
- 是否呼应 meta.theme 与 meta.core_conflict。
- 节奏是否合理(避免前松后紧或中间垮掉)。
- 是否存在明显逻辑硬伤(如年代/制度常识错误)。
- 每条伏笔是否都安排了回收的章节(payoff_chapter 不能一直是 null 却又没有
  在后续任何章节的 beat_summary 里被提及)。

{_JSON_ONLY}
输出格式:{{"passed": true 或 false, "feedback": "若 passed 为 false,给出具体、
可执行的修改意见;若为 true,可留空字符串"}}
"""


CRITIC_OUTPUT_SCHEMA = StateSchema("critic_output", {"passed": bool, "feedback": str})


def build_outline_critic_stage(client: LLMClient) -> Stage:
    agent = _make_agent(client, _OUTLINE_CRITIC_PROMPT, output_schema=CRITIC_OUTPUT_SCHEMA)
    return Stage(
        name="outline_critic",
        executor=agent.run,
        reads=["story_bible.meta", "story_bible.characters"],
        output_schema=CRITIC_OUTPUT_SCHEMA,
    )


# ---------------------------------------------------------------------------
# 3.5.1 大纲人工复核 —— 和 outline_critic 一起串成 ReviewChain,挂进 outline_loop
# 的 critic 槽位:AI 通过后才轮到人工把关,人工不通过时填写的 feedback 与 AI 不
# 通过时一样驱动 outline_generation 重写,下一轮重新走一遍 AI critic + 人工这整
# 条链,而不是只把人工反馈单独拎出去、绕开 AI 复核再走一条独立循环。engine 侧
# 无需为此新增任何原语——这正是 Checkpoint.run() 返回值(inputs 与 resume_input
# 合并)天然是 critic 契约超集、又能被本场景自定义的 ReviewChain 串联的结果。
# ---------------------------------------------------------------------------


def build_outline_human_review_checkpoint() -> Checkpoint:
    return Checkpoint(
        name="confirm_outline",
        resume_input_schema=CRITIC_OUTPUT_SCHEMA,
        prompt="大纲已通过 AI 评审,请确认是否按此大纲进入逐章撰写;不通过请给出修改意见。",
    )


def build_outline_review_chain(client: LLMClient) -> ReviewChain:
    return ReviewChain(
        name="outline_review",
        critics=[build_outline_critic_stage(client), build_outline_human_review_checkpoint()],
    )


# ---------------------------------------------------------------------------
# 3.6 / 3.8 逐章撰写与章节审校(ForEach(chapters, body=Loop(...)))
# ---------------------------------------------------------------------------

CHAPTER_LOOP_ITEM_PATH = "_foreach.chapter_loop.item"

_CHAPTER_DRAFTING_PROMPT = f"""你负责小说创作流程中的"逐章撰写"阶段。
{_STYLE_GUIDE}
输入的 state 中,"{CHAPTER_LOOP_ITEM_PATH}" 是本轮要撰写的这一章的大纲条目
(index/title/beat_summary),"story_bible.chapters" 是全部章节列表(其中下标
更早的章节可能已经有定稿的 draft_summary/text,供你保持衔接;当前章节与之后
的章节仍是占位)。characters/world/foreshadowing 是需要保持一致的既有事实。
如果 inputs 里带着 feedback 字段,说明这是一次修订:请只按 feedback 修改
被指出的问题,不要整章推倒重写。

【句式与节奏】不要通篇用主谓宾短句一句一段地平铺直叙——"我睁开眼。""他问。"
"我说不出话。"这种一行一句、靠动词硬推进度的写法,只能偶尔用在需要"顿"一下
的关键时刻(比如一句对白、一个转折),不能是整章的默认节奏。多数段落应该以
稍长的复合句展开:把环境/氛围(光线、声音、气味、温度这类感官细节)、动作
与人物的心理活动(联想、判断、迟疑、身体感受)编织进同一句或同一段里,让
句子有主次从属关系,而不是把每个细节都拆成单独一句。可以适度使用比喻、
通感等修辞让描写更有质感,但修辞要服务于具体细节,不能滑向空洞抒情或
"仿佛""不禁"式套话。

你的任务:写出本章正文(text),字数落在该章 beat_summary 暗示的篇幅内
(通常 1000-2500 字);同时给出 draft_summary(供后续章节引用的简短摘要),
并把 status 改成 "drafted"。你必须返回**完整的** story_bible.chapters 数组
(把当前 index 对应的那一项替换成新版本,其余章节原样保留,不要丢失)。

{_JSON_ONLY}
输出格式(数组必须包含全部章节,下面只展示当前撰写的这一条该长什么样,
其余章节原样照抄输入里对应的条目):
{{"story_bible.chapters": [{{"index": 1, "title": "...", "beat_summary": "...",
    "draft_summary": "...", "text": "...", "word_count": 0, "status": "drafted"}}],
  "chapter_index": 当前章节的 index,
  "chapter_text": "本章正文,与 chapters 数组里的 text 保持一致,方便审校阶段直接读取"}}
"""


CHAPTER_DRAFTING_OUTPUT_SCHEMA = StateSchema(
    "chapter_drafting_output",
    {"story_bible.chapters": [CHAPTER], "chapter_index": int, "chapter_text": str},
)


def build_chapter_drafting_stage(client: LLMClient) -> Stage:
    agent = _make_agent(
        client,
        _CHAPTER_DRAFTING_PROMPT,
        toolsets=(RESEARCH_TOOLSET,),
        output_schema=CHAPTER_DRAFTING_OUTPUT_SCHEMA,
    )
    return Stage(
        name="chapter_drafting",
        executor=agent.run,
        reads=[
            CHAPTER_LOOP_ITEM_PATH,
            "story_bible.meta",
            "story_bible.characters",
            "story_bible.world",
            "story_bible.foreshadowing",
            "story_bible.chapters",
        ],
        writes=["story_bible.chapters"],
        output_schema=CHAPTER_DRAFTING_OUTPUT_SCHEMA,
    )


_CHAPTER_CRITIC_PROMPT = f"""你负责小说创作流程中的"章节审校"阶段,是 Critic,不负责改写。
{_STYLE_GUIDE}
输入包含刚撰写的 chapter_text / chapter_index,以及 characters/world/timeline/
foreshadowing 供你核对矛盾。

评审维度:
- 一致性:是否与既有人物设定、已确立的时间线/事件矛盾。
- 人物:言行是否符合角色设定与当前弧光阶段。
- 节奏与文笔:是否拖沓/仓促,是否有明显 AI 痕迹(套话、重复句式、空洞形容
  词堆砌),是否偷偷违反了"现实主义、无金手指"的风格要求;是否通篇短句
  一句一段地堆砌、缺少带环境/氛围/心理描写的长句(短句只能用于关键的
  "顿"点,不能是整章默认节奏)——如果存在,视为不通过,并在 feedback 里
  指出具体段落。

{_JSON_ONLY}
输出格式:{{"passed": true 或 false, "feedback": "若 passed 为 false,给出具体、
指向被指出片段的修改意见;若为 true,可留空字符串"}}
"""


def _set_chapter_status(ctx: RunContext, chapter_index: Any, status: str) -> None:
    """把 story_bible.chapters 中下标为 chapter_index 的那一条 status 改写为 status。

    直接经 ctx.state 读写,不走 Stage 的声明式 writes——调用方(chapter_critic /
    chapter_pause)本身的输出契约是 critic 的 {passed, feedback},容不下额外的
    story_bible.chapters 字段,只能以 Node 协议允许的"直接读写 ctx.state"来完成
    这个旁路的状态推进,见 build_chapter_critic_stage / build_chapter_human_review_checkpoint。
    """
    chapters = ctx.state.get("story_bible.chapters", default=[]) or []
    updated_chapters = [
        {**chapter, "status": status} if chapter.get("index") == chapter_index else chapter
        for chapter in chapters
    ]
    ctx.state.patch("story_bible.chapters", updated_chapters)


def build_chapter_critic_stage(client: LLMClient) -> Stage:
    agent = _make_agent(
        client, _CHAPTER_CRITIC_PROMPT, toolsets=(QA_TOOLSET,), output_schema=CRITIC_OUTPUT_SCHEMA
    )

    def executor(ctx: RunContext, inputs: dict[str, Any]) -> dict[str, Any]:
        verdict = agent.run(ctx, inputs)
        # AI 一过审就乐观地把该章 status 推进到 "reviewed",而不是等到
        # chapter_pause 也点头之后才推进——chapter_pause 若选择"暂停保存进度"
        # (见 run.py 的 CheckpointPause 分支),ForEach 会在暂停前先把游标
        # advance 到下一章(engine/primitives/foreach.py 的 except 分支),
        # 导致这一章再也不会被重新访问、chapter_finalize 也不会再跑到它。
        # 乐观地先标 "reviewed" 保证了"卡在断点"不等于"永远卡在 drafted";
        # 人工真的给出不通过意见时,由 chapter_pause 自己把它打回 "drafted"
        # (build_chapter_human_review_checkpoint)。
        if verdict.get("passed"):
            _set_chapter_status(ctx, inputs.get("chapter_index"), "reviewed")
        return verdict

    return Stage(
        name="chapter_critic",
        executor=executor,
        reads=[
            "story_bible.characters",
            "story_bible.world",
            "story_bible.timeline",
            "story_bible.foreshadowing",
        ],
        output_schema=CRITIC_OUTPUT_SCHEMA,
    )


_CHAPTER_REVISION_PROMPT = _CHAPTER_DRAFTING_PROMPT  # 修订与撰写共用同一套约束与输出契约。


def build_chapter_revision_stage(client: LLMClient) -> Stage:
    agent = _make_agent(
        client,
        _CHAPTER_REVISION_PROMPT,
        toolsets=(RESEARCH_TOOLSET,),
        output_schema=CHAPTER_DRAFTING_OUTPUT_SCHEMA,
    )
    return Stage(
        name="chapter_revision",
        executor=agent.run,
        reads=[
            CHAPTER_LOOP_ITEM_PATH,
            "story_bible.meta",
            "story_bible.characters",
            "story_bible.world",
            "story_bible.foreshadowing",
            "story_bible.chapters",
        ],
        writes=["story_bible.chapters"],
        output_schema=CHAPTER_DRAFTING_OUTPUT_SCHEMA,
    )


# ---------------------------------------------------------------------------
# 3.8.0.1 章节人工复核 —— 与 build_outline_review_chain 同样的手法:和
# chapter_critic 串成 ReviewChain 挂进 chapter_review_loop 的 critic 槽位,
# AI 评审通过后才轮到人工把关;人工的 feedback 与 AI 不通过时一样驱动
# chapter_revision 重写本章,下一轮重新走一遍 AI + 人工这整条链,而不是等
# 这一章被判定完成、状态推进到 "reviewed" 之后才发现要返工。
# ---------------------------------------------------------------------------


class _ChapterHumanReviewCheckpoint:
    """包一层 Checkpoint:人工给出"不通过"时把该章 status 从 chapter_critic 乐观
    写入的 "reviewed" 打回 "drafted",驱动 chapter_review_loop 下一轮重新修订;
    通过、或尚未决定就暂停(见 run.py 的 "q" 分支)时都保留 "reviewed"——
    "暂停"不代表"不通过",不该把还没被人工否决的章节退回 drafted。

    仍然是名副其实的 Node(name + run),可以像原生 Checkpoint 一样直接塞进
    ReviewChain.critics;暂停/恢复的机制(ctx.resume 认领、CheckpointPause)
    完全委托给内部持有的这个真正的 engine Checkpoint,这里只在其返回之后补一刀
    状态写回,不侵入引擎的暂停语义。
    """

    def __init__(self, checkpoint: Checkpoint) -> None:
        self._checkpoint = checkpoint
        self.name = checkpoint.name

    def run(self, ctx: RunContext, inputs: dict[str, Any]) -> dict[str, Any]:
        result = self._checkpoint.run(ctx, inputs)
        if not result.get("passed"):
            _set_chapter_status(ctx, result.get("chapter_index"), "drafted")
        return result


def build_chapter_human_review_checkpoint() -> Node:
    checkpoint = Checkpoint(
        name="chapter_pause",
        resume_input_schema=CRITIC_OUTPUT_SCHEMA,
        prompt="本章已通过 AI 审校,请确认是否继续下一章;不通过请给出修改意见。",
    )
    return _ChapterHumanReviewCheckpoint(checkpoint)


def build_chapter_review_chain(client: LLMClient) -> ReviewChain:
    return ReviewChain(
        name="chapter_review",
        critics=[build_chapter_critic_stage(client), build_chapter_human_review_checkpoint()],
    )


# ---------------------------------------------------------------------------
# 3.8.1 章节定稿 —— 兜底把该章 status 推进到 "reviewed"。正常路径下
# chapter_critic 一过审就已经乐观地把 status 写成 "reviewed"(见
# build_chapter_critic_stage 顶部的说明),这里再写一遍是幂等的;真正依赖
# 这一步的是 chapter_review_loop 超过 max_iterations、按
# on_exceed=escalate_to_checkpoint 升级为人工裁决后"自动接受最后一版"的路径
# ——那条路径不经过 chapter_critic 的最终通过判定,该章此时仍停在 "drafted",
# 要靠这里推一把才能继续往下一章走。纯函数 executor,不需要 LLM。
# ---------------------------------------------------------------------------


def chapter_finalize_executor(ctx: RunContext, inputs: dict[str, Any]) -> dict[str, Any]:
    current_index = (inputs.get("state", {}).get(CHAPTER_LOOP_ITEM_PATH) or {}).get("index")
    _set_chapter_status(ctx, current_index, "reviewed")
    return {}


def build_chapter_finalize_stage() -> Stage:
    return Stage(
        name="chapter_finalize",
        executor=chapter_finalize_executor,
        reads=[CHAPTER_LOOP_ITEM_PATH],
    )


# ---------------------------------------------------------------------------
# 3.9 全文统稿与润色
# ---------------------------------------------------------------------------

_MANUSCRIPT_POLISH_PROMPT = f"""你负责小说创作流程中的"全文统稿与润色"阶段。
{_STYLE_GUIDE}
输入包含全部 story_bible.chapters 与 story_bible.foreshadowing。
你的任务:
1. 检查跨章问题:称呼/术语前后是否一致、语气是否漂移、是否有重复的意象或
   转折模式——如有,直接在对应章节的 text 里做最小必要的修订。
2. 伏笔回收检查:遍历 foreshadowing,把已在某章正文中回收的项标记为
   resolved(补上 payoff_chapter),确认不再需要的可标记为 dropped,但不能让
   状态一直悬空在 planted 却已过了计划回收的章节。

{_JSON_ONLY}
输出格式(两个数组都必须包含全部条目,下面只展示元素该长什么样,
没有改动的条目原样照抄输入,只对确实要改的条目做最小必要修订):
{{"story_bible.chapters": [{{"index": 1, "title": "...", "beat_summary": "...",
    "draft_summary": "...", "text": "...", "word_count": 0, "status": "drafted"}}],
  "story_bible.foreshadowing": [{{"id": "...", "planted_in_chapter": 1,
    "description": "...", "payoff_chapter": 5, "status": "resolved"}}]}}
"""


MANUSCRIPT_ASSEMBLY_POLISH_OUTPUT_SCHEMA = StateSchema(
    "manuscript_assembly_polish_output",
    {"story_bible.chapters": [CHAPTER], "story_bible.foreshadowing": [FORESHADOWING]},
)


def build_manuscript_assembly_polish_stage(client: LLMClient) -> Stage:
    agent = _make_agent(
        client,
        _MANUSCRIPT_POLISH_PROMPT,
        output_schema=MANUSCRIPT_ASSEMBLY_POLISH_OUTPUT_SCHEMA,
    )
    return Stage(
        name="manuscript_assembly_polish",
        executor=agent.run,
        reads=["story_bible.chapters", "story_bible.foreshadowing", "story_bible.meta"],
        writes=["story_bible.chapters", "story_bible.foreshadowing"],
        output_schema=MANUSCRIPT_ASSEMBLY_POLISH_OUTPUT_SCHEMA,
    )


# ---------------------------------------------------------------------------
# 3.10 最终校验与输出 —— 同样是纯函数 executor,不需要 LLM。
# ---------------------------------------------------------------------------


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


def build_final_qa_stage() -> Stage:
    return Stage(
        name="final_qa",
        executor=final_qa_executor,
        reads=["story_bible.chapters", "story_bible.meta"],
        writes=["story_bible.chapters"],
    )


# ---------------------------------------------------------------------------
# 组装:把以上节点注册进 NodeRegistry,供 workflow.py 的 from_spec 按名引用。
#
# 注意登记表收的是 **Node 而非 Stage**:下面既有 Stage(叶子,真正产出内容),
# 也有 Checkpoint(引擎原语)和 ReviewChain(本场景自定义的组合节点)。三者
# 唯一的共同点就是都满足 Node 协议——workflow.yaml 里按名引用它们时,也完全
# 看不出彼此的区别。这正是 Node 被抽象成 Protocol 的意义所在。
# ---------------------------------------------------------------------------

STAGE_NAMES_NEEDING_LLM = (
    "concept_expansion",
    "character_world_design",
    "outline_generation",
    "outline_critic",
    "chapter_drafting",
    "chapter_critic",
    "chapter_revision",
    "manuscript_assembly_polish",
)


def build_node_registry(client_factory: ClientFactory):
    """组装本场景全部节点(Stage / Checkpoint / ReviewChain),注册进一个新的 NodeRegistry。

    Args:
        client_factory: 按节点名取一个 LLMClient 的工厂函数。真实运行通常
            对所有名字返回同一个 client;线下演示按名字返回预置好回复的
            ScriptedLLMClient(见 offline_demo.py)。
    """
    # 延迟导入,避免 stages.py 与 workflow.py 之间产生循环导入。
    from engine.workflow import NodeRegistry

    registry = NodeRegistry()
    registry.register(build_input_parsing_stage())
    registry.register(build_concept_expansion_stage(client_factory("concept_expansion")))
    registry.register(
        build_character_world_design_stage(client_factory("character_world_design"))
    )
    registry.register(build_outline_generation_stage(client_factory("outline_generation")))
    registry.register(build_outline_review_chain(client_factory("outline_critic")))
    registry.register(build_chapter_drafting_stage(client_factory("chapter_drafting")))
    registry.register(build_chapter_review_chain(client_factory("chapter_critic")))
    registry.register(build_chapter_revision_stage(client_factory("chapter_revision")))
    registry.register(build_chapter_finalize_stage())
    registry.register(
        build_manuscript_assembly_polish_stage(client_factory("manuscript_assembly_polish"))
    )
    registry.register(build_final_qa_stage())
    return registry


__all__ = [
    "STORY_BIBLE_SCHEMA",
    "ClientFactory",
    "CHAPTER_LOOP_ITEM_PATH",
    "build_node_registry",
]
