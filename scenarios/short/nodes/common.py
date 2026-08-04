"""跨 Node 复用的公用组件:Agent 组装、状态路径常量、评审判定合并等。

三条贯穿全场景的约定(原 stages.py 模块 docstring,拆分后仍然成立):

1. **prompt 一律来自 prompts.py**,各 Node 模块不写任何 prompt 文本;prompts.py
   里也不写任何题材内容(那些在用户的 brief.yaml 里)。这就是需求里"用户输入的
   prompt 与流程使用的 prompt 要分开"在代码上的落点。

2. **模型只产出它真正创作的那部分,拼装交给代码。** 与 scenarios/novel 不同,
   撰写类节点不要求模型"原样回显整个 sections 数组":它只返回本节的 text 与
   summary,由 executor 读出当前数组、替换掉这一节、把整份新数组作为 Stage 的
   输出交给声明式的 writes 写回。于是每个 LLM 节点有两份 schema:给 Agent 的
   (模型该吐什么)和给 Stage 的(写回状态的是什么),职责不同,不该合并。

3. **能算的不交给模型判断。** 字数、句长分布、单句成段比例、套话密度、大纲的
   编号与预算合计,全部由 toolsets/ 里的确定性函数先算一遍;算出的问题无条件
   并进 Critic 的判定(见 _merge_verdict),模型只负责它算不出来的部分。
"""

from __future__ import annotations

from typing import Any, Callable

from agent.agent import Agent
from agent.memory import ConversationMemory
from engine.context import RunContext
from llm.client import LLMClient
from state.schema import StateSchema
from tools.registry import ToolRegistry

# 由调用方(run.py)提供:按 (节点名, 生效 model) 给出一个 LLMClient。
ClientFactory = Callable[[str, str | None], LLMClient]

_DEFAULT_MAX_STEPS = 6

# 评审类节点的判定字段名。极性朝着"还要再改一轮"为真——Loop 的 continue_when 是
# 一条裸状态路径,引擎只取真假,没有取反的余地(见 engine/primitives/loop.py)。
NEEDS_REVISION_KEY = "needs_revision"

# 状态路径(手写常量;场景内手写状态路径字符串常量与 schema 定义两处维护的问题
# 本次不解决,继续沿用这个写法)。
BRIEF_PATH = "short_story.brief"
META_PATH = "short_story.meta"
CHARACTERS_PATH = "short_story.characters"
PAYOFFS_PATH = "short_story.payoffs"
SECTIONS_PATH = "short_story.sections"

CRITIC_OUTPUT_SCHEMA = StateSchema("critic_output", {NEEDS_REVISION_KEY: bool, "feedback": str})


def make_agent(
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


def ask(agent: Agent, ctx: RunContext, payload: dict[str, Any]) -> dict[str, Any]:
    """把 payload 交给 Agent 跑一次,并保证每次都从干净的对话记忆开始。

    节点只造一次 Agent,而 ForEach 会让同一个 Agent 实例被每一节复用。不清空
    记忆的话,第 N 节的请求里会拖着前 N-1 节的全部正文与评审意见:开销随节数
    累积是小事,真正的麻烦是模型会顺着自己上一节的句式继续写——那正是我们要防
    的"AI 痕迹"。跨节需要的连贯性一律走 State(前情摘要、上一节结尾原文、骨架
    设定),不靠对话历史。
    """
    agent.memory.messages = []
    return agent.run(ctx, payload)


def merge_verdict(verdict: dict[str, Any], auto_problems: list[str]) -> dict[str, Any]:
    """把"确定性体检发现的问题"与"LLM Critic 的意见"合成一份判定。

    确定性问题一票否决:只要有一条,不管模型说什么都判否,并把问题原文放进
    feedback——下一轮的撰写/精修节点会照着它改。模型的意见附在后面,不丢弃。
    """
    llm_feedback = str(verdict.get("feedback") or "").strip()
    if auto_problems:
        parts = ["【确定性体检(必须改)】"] + [f"- {p}" for p in auto_problems]
        if llm_feedback:
            parts += ["【审校意见】", llm_feedback]
        return {NEEDS_REVISION_KEY: True, "feedback": "\n".join(parts)}
    return {NEEDS_REVISION_KEY: bool(verdict.get(NEEDS_REVISION_KEY)), "feedback": llm_feedback}


def feedback_from(state: dict[str, Any], cursor_path: str) -> str:
    """从 Loop 游标里取上一轮的评审意见;首轮(游标为空)返回空串。"""
    return str(((state.get(cursor_path) or {}).get("feedback") or "")).strip()


def story_context(state: dict[str, Any]) -> dict[str, Any]:
    """骨架 + 角色 + 爽点设计——每个写作/审校节点都要看的那份全局事实。"""
    return {
        "meta": state.get(META_PATH) or {},
        "characters": state.get(CHARACTERS_PATH) or [],
        "payoffs": state.get(PAYOFFS_PATH) or [],
    }
