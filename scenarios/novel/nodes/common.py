"""跨 Node 复用的公用组件:Agent 组装、状态路径常量、评审判定 schema。

与 scenarios/short 的一处刻意不同:这里的 make_agent 不提供"每次调用清空对话
记忆"的包装(对比 scenarios/short/nodes/common.py 的 ask())。逐章撰写等节点的
Agent 在整个流程里只造一次、被 chapter_loop 的每一次迭代复用,记忆是否清空是
一个真实的行为差异,不是"声明式换成纯 Python 组装"这次改动应该顺带改掉的东西
——两个场景各自的选择见 scenarios/short/README.md"与 novel 场景的其他差别"一节。
"""

from __future__ import annotations

from typing import Any, Callable

from agent.agent import Agent
from agent.memory import ConversationMemory
from agent.toolset import ToolSet
from engine.context import RunContext
from llm.client import LLMClient
from state.schema import StateSchema
from tools.registry import ToolRegistry

# 由调用方(run.py/offline_demo.py)提供:按 (节点名, 生效 model) 给出一个 LLMClient。
ClientFactory = Callable[[str, str | None], LLMClient]

# 8 步足够"查两次考据 + 产出",再多通常是模型在原地打转(见 agent/agent.py 对
# max_steps 耗尽的告警)。
_DEFAULT_MAX_STEPS = 8

# 评审类节点(AI critic 与人工 Checkpoint)的判定字段名。极性刻意朝着"还要再改
# 一轮"为真(如 outline_loop/chapter_review_loop 的 continue_when 都是
# needs_revision_continue_when),便于沿用"真=还要重开一轮"这条约定俗成。
NEEDS_REVISION_KEY = "needs_revision"
CRITIC_OUTPUT_SCHEMA = StateSchema("critic_output", {NEEDS_REVISION_KEY: bool, "feedback": str})


def needs_revision_continue_when(ctx: RunContext, outputs: dict[str, Any]) -> bool:
    """本场景两个 Loop(outline_loop / chapter_review_loop)共用的判定谓词。

    Loop 在 body 里每个节点跑完后都会调用一次这个谓词(不只是评审节点那一个),
    所以用 .get(..., False) 而不是 outputs[...]——生成类节点的 outputs 里没有
    这个字段,.get 的默认值 False 让它不会被误判成"要求重开一轮"。
    """
    return outputs.get(NEEDS_REVISION_KEY, False)

# 状态路径。
META_PATH = "story_bible.meta"
CHARACTERS_PATH = "story_bible.characters"
WORLD_PATH = "story_bible.world"
TIMELINE_PATH = "story_bible.timeline"
FORESHADOWING_PATH = "story_bible.foreshadowing"
CHAPTERS_PATH = "story_bible.chapters"


def make_agent(
    client: LLMClient,
    system_prompt: str,
    toolsets: tuple[ToolSet, ...] = (),
    output_schema: StateSchema | None = None,
) -> Agent:
    agent = Agent(
        client=client,
        memory=ConversationMemory(system_prompt=system_prompt),
        registry=ToolRegistry(),
        max_steps=_DEFAULT_MAX_STEPS,
        output_schema=output_schema,
    )
    for toolset in toolsets:
        agent.load_toolset(toolset)
    return agent
