"""不需要真实 API Key 也能跑通的完整流水线演示。

run.py 需要 ANTHROPIC_API_KEY/OPENAI_API_KEY 才能工作,但"这套接线到底通不通"
应该不依赖网络和账单。这里给每个需要 LLM 的 Stage 配一个
ScriptedLLMClient(与 tests/agent/test_agent.py 用的手法一致):预先写好这一次
要"生成"的内容,严格按各 Stage 在 stages.py 里约定的 JSON 契约打包成响应。
Critic 类 Stage 统一脚本成 {"passed": true},所以 Loop 一次通过、不触发
reviser——这是为了让"跑通全流程"这件事在没有真实模型判断力的情况下依然
确定性可复现,不代表真实运行时 Loop 不会修订。

跑一遍这个脚本,得到的不是"假数据占位符",而是本场景第一版参考实现真正要
交付的内容:第一章《初到西汉》,一名现代历史系研究生跌进西汉建元年间长安、
在无所依凭的处境里第一次被这个时代"教做人"的开篇。大纲里目前只规划了这一
章——按 docs/workflow-design.md 的设计,中短篇应有 6-15 章,后续章节(包括
随张骞出使西域的部分)留待下一轮迭代继续写,不在这一版里硬凑。

用法:

    python -m scenarios.novel.offline_demo
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from engine.context import CheckpointRequest, LifecycleHooks, RunContext
from llm.client import ChatResponse, LLMClient
from llm.message import Message
from state.backends.memory import InMemoryStateStore

from scenarios.novel.landing import land_output
from scenarios.novel.state_schema import empty_state
from scenarios.novel.workflow import build_workflow

DEFAULT_BRIEF_PATH = Path(__file__).with_name("brief.yaml")
DEFAULT_OUTPUT_DIR = Path(__file__).with_name("output")


class ScriptedLLMClient(LLMClient):
    """按顺序吐出预先写好的 ChatResponse;用完会报错,便于发现意料之外的额外调用。"""

    def __init__(self, responses: list[ChatResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[list[Message]] = []

    def chat(self, messages: list[Message], tools=None, **params: Any) -> ChatResponse:
        self.calls.append(list(messages))
        if not self._responses:
            raise AssertionError("ScriptedLLMClient 的预置回复已用完(出现了未预期的额外调用)")
        return self._responses.pop(0)


def _final(payload: dict[str, Any]) -> ChatResponse:
    content = json.dumps(payload, ensure_ascii=False)
    return ChatResponse(message=Message(role="assistant", content=content))


def _passed(feedback: str = "") -> ChatResponse:
    return _final({"passed": True, "feedback": feedback})


# ---------------------------------------------------------------------------
# 第一章正文 —— 这是本次演示真正的创作产出,不是占位符。
# ---------------------------------------------------------------------------

CHAPTER_1_TEXT = """水呛得我肺里像塞满了碎玻璃。

我睁开眼时先看见的是天,不是我认识的那种天——没有一丝电线、没有航迹云,灰蒙蒙的,像蒙了一层没洗干净的布。然后是疼,从后脑到脊椎一寸一寸地疼过去,像是刚被人从很高的地方扔下来又捞起来。

我试着抬手擦脸,看见的却是一只不属于我的手:指节粗大,虎口有一道旧疤,指甲缝里嵌着洗不掉的黑泥。我盯着这只手看了很久,直到旁边有人用一种我从没听过、却又莫名能听懂七八分的腔调骂了一句什么,才想起自己应该站起来。

我是苏亦,二十六岁,历史系在读研究生,论文题目是《河西走廊交通线与张骞西域之行考》。至少三秒钟前,我还是这个人。现在我泡在一条散发着腥臭的水沟里,身上裹着一件不知道被多少人穿过的粗麻衣,水沟对岸蹲着一个正在剖洗猪下水的中年男人,面无表情地看着我,像在看一件从上游漂下来、还没决定要不要捞的浮木。

"你是打哪儿冒出来的?"他终于开口,声音很粗,带着一种我后来才知道该叫"关中土话"的调子,"这渠里前几日才捞出去一个,你又来一个。"

我张嘴想说"我不知道,我可能穿越了",话到嘴边却发现自己的舌头不听使唤——不是说不出话,是这具身体的口腔、喉咙的肌肉记忆和我脑子里想说的东西对不上。我听见自己发出的是一串含混的、带着这具身体主人乡音的音节,连我自己都听不懂在说什么。

那个屠户皱起眉,像是听出了什么不对劲。他后来告诉我,他当时以为我是"失心疯",要么就是被打懵了,舌头都捋不直。

他叫陈阿福,是长安东市屠肆里排第三档的屠户,当天来渠边不是为了别的,是来倒猪下水的——这是我到长安的第一课:没有下水道,污水和内脏都往城外的明渠里倒,而我恰好从这条渠里"醒"了过来,占据了一个前几天在这附近溺水而亡的年轻人的身体。陈阿福后来又说,那具尸体停在渠边整整两天没人认领,他还纳闷怎么忽然自己爬起来了。

他没有把我当鬼看,这一点我后来想明白了才觉得庆幸——按这个时代的观念,水鬼诈尸是要被打杀了扔回渠里的。他只是蹲下来,伸手在我鼻子底下探了探气,又扒开我的眼皮看了看,嘟囔了一句"魂儿没散全,倒是走了大运",然后把我拖上岸。

我浑身发抖,不全是因为冷——虽然确实冷,深秋的关中,湿透的麻衣贴在身上像一层冰——更多是因为一种迟到的、完整的恐慌:我意识到自己没有手机,没有身份证,没有任何能证明"我是谁"的东西,而这具身体的舌头还不完全听我使唤。我张了张嘴,想说"谢谢",发出来的却是一个短促的、几乎是婴儿呀呀学语般的音。

陈阿福盯着我看了半天,忽然骂了一句脏话,把身上的一件旧褐衣解下来扔给我:"穿上,别在这儿冻死,冻死了我还得报官。"

这句话我后来反复咂摸过。他救我,一半是恻隐,一半是不想惹上"渠边发现死人"这种要报官验尸、还可能被诬赖"谋杀"的麻烦事——报官在这个时代从来不是一件轻松的事,尤其对一个市籍屠户来说。

他把我带回家,一个在东市外围、只有两间土坯房的窄小院子。他的妻子看见我时的表情,和我预想的"哦一个可怜人"完全不一样——她先是愣住,然后死死盯着陈阿福,那眼神我一个现代人都读得懂:你脑子有病吗,平白无故往家里领一个来历不明的人?

那天晚上,我第一次吃到这个时代的饭:一小碗粟米粥,几乎看不见几粒米,飘着几片腌菜的叶子,咸得发苦。没有桌子,一家人蹲在门槛内外就着一个矮木案分食,我学着他们的样子跪坐下去,大腿很快就麻了。陈阿福的妻子始终没跟我说话,只在给我盛粥的时候,用眼角瞟了一下我这件借来的旧褐衣,又瞟了一下我沉默的脸,像是在确认一件事:这个人不对劲。

我不敢开口——一开口就是破绽,谁知道我这具身体的方言会不会又冒出几个字眼把我出卖。可越是沉默,我在他们眼里就越像一个哑巴,或者更糟,一个被吓破了魂、说不清来历的疯子。

第二天一早,麻烦就来了。

我正跟着陈阿福学着劈柴——手忙脚乱,握斧的姿势都要模仿这具身体残留的一点肌肉记忆——院外传来一阵脚步声和皮质佩件碰撞的轻响。是这一里的亭长张越,带着一个记事的小吏,例行按什伍名籍挨家点卯,顺带盘查有没有面生的外人。

"陈阿福,家里添了人?"张越站在院门口,眼睛已经落在我身上,"传呢?"

传,就是通行的凭证——没有它,我就是一个凭空冒出来、无法解释自己从哪儿来的"亡人",在这套户籍连坐的体系里,这样的人本身就是一种罪证。

陈阿福张了张嘴,想替我圆一句"是我远房侄子",可他自己也说不清我姓甚名谁、籍贯何处。我看着他为难的样子,又看着张越身后那个小吏已经掏出简牍准备记录,忽然意识到,昨晚那种"活下来就好"的侥幸,到今天早上已经用完了。

"叫什么名字?"张越问我,目光锐利。

我张开嘴,这一次,连含混的乡音都没能发出来——我彻底不知道该说"苏亦",还是说出这具身体原本的名字,而我压根不知道那个名字是什么。

沉默维持得太久,张越的脸色沉了下去。他冲小吏使了个眼色:"先记下,带回亭里问话。\""""


def build_scripted_client_factory():
    """按 Stage 名给每个需要 LLM 的 Stage 配一个装好回复的 ScriptedLLMClient。"""

    responses: dict[str, ChatResponse] = {
        "concept_expansion": _final(
            {
                "story_bible.meta": {
                    "logline": (
                        "一名研究张骞出使西域的历史系研究生突然跌进公元前139年的长安,"
                        "占据了一具陌生的躯体,必须先学会怎样在森严的礼法与随时可能因"
                        "'来历不明'获罪的处境里活下去,再决定要不要真的踏上他曾经只能在"
                        "竹简里读到的那条西行路。"
                    ),
                    "theme": (
                        "历史不是可以安全旁观的过去——真正'亲历'一段历史,意味着放弃"
                        "旁观者的距离感,用具体的、会犯错会害怕的身体去承受它。"
                    ),
                    "core_conflict": (
                        "苏亦想凭着'我知道历史走向'活下去、甚至趋利避害,却发现西汉的"
                        "礼法、户籍连坐与生存逻辑根本不按'历史书的剧透'运转——他必须"
                        "放弃'穿越者优势'的幻觉,像一个真正一无所有的汉代人那样重新"
                        "学习活着。"
                    ),
                }
            }
        ),
        "character_world_design": _final(
            {
                "story_bible.meta": {"title": "凿空"},
                "story_bible.characters": [
                    {
                        "id": "char_01",
                        "name": "苏亦",
                        "role": "protagonist",
                        "goal": "先活下去,再弄清楚自己能否、要不要回去",
                        "motivation": "对张骞出使西域这段历史的学术执念,不甘心只做旁观者",
                        "flaw": "惯于用'我知道结局'的优越感应对陌生处境,容易轻慢眼前具体的人和具体的风险",
                        "arc": "从'把西汉当研究材料'到'把眼前人当活生生的人对待,并接受自己可能回不去'",
                        "relationships": [{"target_id": "char_02", "relation": "收留人/临时依靠"}],
                        "status_log": [],
                    },
                    {
                        "id": "char_02",
                        "name": "陈阿福",
                        "role": "supporting",
                        "goal": "不惹麻烦地把日子过下去,不让家里因为多余的善意惹祸",
                        "motivation": "市井生存哲学:能帮就帮一把,但绝不能自己搭进去",
                        "flaw": "心软但胆小,遇事容易退缩",
                        "arc": "从'不愿意惹麻烦'到'愿意为苏亦担一次风险'",
                        "relationships": [{"target_id": "char_01", "relation": "收留的来历不明者"}],
                        "status_log": [],
                    },
                    {
                        "id": "char_03",
                        "name": "张越",
                        "role": "antagonist",
                        "goal": "把辖内户籍核实清楚,不给自己惹麻烦",
                        "motivation": "基层小吏的自保与晋升焦虑",
                        "flaw": "教条,把规章当成唯一的正确",
                        "arc": "(留待后续章节展开)",
                        "relationships": [],
                        "status_log": [],
                    },
                ],
                "story_bible.world": [
                    {
                        "id": "world_01",
                        "name": "长安户籍与路引制度",
                        "description": "乡里编入什伍、互相连坐监督;离乡远行需官府发给的'传'作通行凭证,无凭证者视为'亡人'扣押盘问。",
                        "established_in_chapter": 1,
                    },
                    {
                        "id": "world_02",
                        "name": "长安东市与屠肆",
                        "description": "东市按行业分肆经营,屠户在市中排档位;城内无下水道,污秽与屠宰下水多倒入城外明渠。",
                        "established_in_chapter": 1,
                    },
                    {
                        "id": "world_03",
                        "name": "张骞出使西域(建元年间)",
                        "description": "武帝欲联合大月氏东西夹击匈奴,募人出使,郎官张骞应募——此时尚未启程,是苏亦后续故事线的历史出口。",
                        "established_in_chapter": 1,
                    },
                ],
            }
        ),
        "outline_generation": _final(
            {
                "story_bible.chapters": [
                    {
                        "index": 1,
                        "title": "初到西汉",
                        "beat_summary": (
                            "苏亦在东市外的明渠边苏醒,发现自己占据了一具溺亡青年的身体;"
                            "被屠户陈阿福搭救、带回家过夜,亲身感受没有'穿越者优势'的西汉——"
                            "寒冷、饥饿、语言隔阂、寄人篱下的窘迫;次日晨,亭长张越按什伍名籍"
                            "例行盘查,他因答不出传符与姓名,被记下带走问话。"
                        ),
                        "draft_summary": "",
                        "text": "",
                        "word_count": 0,
                        "status": "planned",
                    }
                ],
                "story_bible.foreshadowing": [
                    {
                        "id": "fs_01",
                        "planted_in_chapter": 1,
                        "description": "苏亦说话时偶尔带着不合时宜的腔调和用词,被亭长张越注意到并记在心里",
                        "payoff_chapter": None,
                        "status": "planted",
                    }
                ],
            }
        ),
        "outline_critic": _passed(),
        "chapter_drafting": _final(
            {
                "story_bible.chapters": [
                    {
                        "index": 1,
                        "title": "初到西汉",
                        "beat_summary": (
                            "苏亦在东市外的明渠边苏醒,发现自己占据了一具溺亡青年的身体;"
                            "被屠户陈阿福搭救、带回家过夜,亲身感受没有'穿越者优势'的西汉——"
                            "寒冷、饥饿、语言隔阂、寄人篱下的窘迫;次日晨,亭长张越按什伍名籍"
                            "例行盘查,他因答不出传符与姓名,被记下带走问话。"
                        ),
                        "draft_summary": (
                            "苏亦溺水后夺舍苏醒于东市明渠边,被屠户陈阿福收留过夜;"
                            "次日晨,亭长张越按名籍盘查传符,他因答不出姓名来历,被记下带走问话。"
                        ),
                        "text": CHAPTER_1_TEXT,
                        "word_count": 0,
                        "status": "drafted",
                    }
                ],
                "chapter_index": 1,
                "chapter_text": CHAPTER_1_TEXT,
            }
        ),
        "chapter_critic": _passed(),
        "manuscript_assembly_polish": _final(
            {
                "story_bible.chapters": [
                    {
                        "index": 1,
                        "title": "初到西汉",
                        "beat_summary": (
                            "苏亦在东市外的明渠边苏醒,发现自己占据了一具溺亡青年的身体;"
                            "被屠户陈阿福搭救、带回家过夜,亲身感受没有'穿越者优势'的西汉——"
                            "寒冷、饥饿、语言隔阂、寄人篱下的窘迫;次日晨,亭长张越按什伍名籍"
                            "例行盘查,他因答不出传符与姓名,被记下带走问话。"
                        ),
                        "draft_summary": (
                            "苏亦溺水后夺舍苏醒于东市明渠边,被屠户陈阿福收留过夜;"
                            "次日晨,亭长张越按名籍盘查传符,他因答不出姓名来历,被记下带走问话。"
                        ),
                        "text": CHAPTER_1_TEXT,
                        "word_count": 0,
                        "status": "reviewed",
                    }
                ],
                "story_bible.foreshadowing": [
                    {
                        "id": "fs_01",
                        "planted_in_chapter": 1,
                        "description": "苏亦说话时偶尔带着不合时宜的腔调和用词,被亭长张越注意到并记在心里",
                        "payoff_chapter": None,
                        "status": "planted",
                    }
                ],
            }
        ),
    }

    def factory(stage_name: str, _model: str | None) -> LLMClient:
        # build_node_registry 会为 workflow.yaml 里提到的每个 Stage 名字都建一个
        # Agent(哪怕它在这次演示里实际不会被调用,比如 chapter_revision——本次
        # 演示的 critic 一次就通过,不会触发 reviser)。没预置回复的 Stage 给一个
        # 空列表:只要它真的不被调用就没事,一旦被调用会因为"用完了"而报错,
        # 提醒开发者补一条脚本回复,而不是默默返回不相关的内容。_model(见
        # engine.workflow.Workflow.resolve_stage_models)在离线演示里没有意义
        # ——脚本化回复不真的调用任何模型,忽略即可。
        response = responses.get(stage_name)
        return ScriptedLLMClient([response] if response is not None else [])

    return factory


def _auto_checkpoint_handler(request: CheckpointRequest) -> dict[str, Any]:
    print(f"[checkpoint:auto] {request.name} -> 自动通过(离线演示不做交互式确认)")
    if request.name in ("confirm_outline", "chapter_pause"):
        # confirm_outline / chapter_pause 现在是各自 Loop 的 critic,
        # 契约是 {"passed", "feedback"}(见 stages.py 的 human review checkpoint)。
        return {"passed": True, "feedback": ""}
    return request.context or {}


def run_offline_demo(output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, Path]:
    """跑一遍完整流水线(脚本化 LLM 回复),把结果落地到 output_dir。"""
    with open(DEFAULT_BRIEF_PATH, "r", encoding="utf-8") as f:
        brief = yaml.safe_load(f)

    workflow = build_workflow(client_factory=build_scripted_client_factory())
    state_store = InMemoryStateStore(initial=empty_state())
    ctx = RunContext(
        state=state_store,
        checkpoint_handler=_auto_checkpoint_handler,
        hooks=LifecycleHooks(
            before_stage=lambda name, _inputs: print(f"[stage:start] {name}"),
            after_stage=lambda name, _outputs: print(f"[stage:done]  {name}"),
        ),
    )

    outputs = workflow.run(ctx, brief)
    written = land_output(state_store.snapshot(), output_dir)

    print("\n已落地产物:")
    for label, path in written.items():
        print(f"  {label}: {path}")
    print("\nfinal_qa 报告:", outputs.get("qa_report"))
    return written


if __name__ == "__main__":
    run_offline_demo()
