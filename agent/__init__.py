"""Agent 与 ToolSet —— 场景能力的挂载点(docs/framework-design.md §4)。

Agent = LLM Client + ToolRegistry + ToolSets(工具集) + Memory。
它是 Stage 的典型执行体(executor)。给同一个抽象 Stage 挂载不同 ToolSet,
就得到不同场景下的能力——这正是"二次开发只需装 ToolSet"的核心机制。

注意:这里的 ToolSet 是代码装配期显示挂载的一组 (tool_func, schema),
与 Claude/OpenAI 的 "Skill"(运行时由模型自主发现/渐进式加载的磁盘目录)
是不同层次的概念,不要混用。

    Agent  —— 执行体:驱动一次 LLM + 工具调用循环完成 Stage
    ToolSet  —— 一组 (tool_func, schema),可加载进 Agent
    ConversationMemory —— Agent 的对话记忆
"""

from agent.agent import Agent
from agent.toolset import ToolSet
from agent.memory import ConversationMemory

__all__ = ["Agent", "ToolSet", "ConversationMemory"]
