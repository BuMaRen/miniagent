"""Agent 与 Skill —— 场景能力的挂载点(docs/framework-design.md §4)。

Agent = LLM Client + ToolRegistry + Skills(工具集) + Memory。
它是 Stage 的典型执行体(executor)。给同一个抽象 Stage 挂载不同 Skill,
就得到不同场景下的能力——这正是"二次开发只需装 Skill"的核心机制。

    Agent  —— 执行体:驱动一次 LLM + 工具调用循环完成 Stage
    Skill  —— 一组 (tool_func, schema),可加载进 Agent
    ConversationMemory —— Agent 的对话记忆
"""

from agent.agent import Agent
from agent.skill import Skill
from agent.memory import ConversationMemory

__all__ = ["Agent", "Skill", "ConversationMemory"]
