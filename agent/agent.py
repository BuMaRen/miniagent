"""Agent —— Stage 的典型执行体(docs/framework-design.md §4)。

Agent 把 LLM、工具、技能、记忆组装在一起,内部驱动一个 agentic loop
(模型思考 -> 调用工具 -> 观察结果 -> 继续,直到产出最终输出)来完成一个 Stage。
它对外暴露成 engine.stage.Executor 的签名 (ctx, inputs) -> outputs。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent.skill import Skill
from agent.memory import ConversationMemory
from llm.client import LLMClient
from tools.registry import ToolRegistry
from tools.executor import ToolExecutor


@dataclass
class Agent:
    """一个可执行的智能体。

    Attributes:
        client:       LLM 客户端(见 llm/client.py)。
        registry:     工具注册表。
        executor:     工具执行器。
        memory:       对话记忆。
        skills:       已加载的技能列表。
        max_steps:    单次运行内 agentic loop 的最大步数,防止失控。
    """

    client: LLMClient
    registry: ToolRegistry
    executor: ToolExecutor
    memory: ConversationMemory
    skills: list[Skill] = field(default_factory=list)
    max_steps: int = 12

    def load_skill(self, skill: Skill, mode: str = "append") -> None:
        """加载一个 Skill:把其工具注册进 registry。

        Args:
            skill: 待加载技能。
            mode:  "append" 保留已有工具(默认);"replace" 先清空再加载。
        """
        # TODO:
        #   - mode == "replace" 时清空 registry 中由 Skill 注册的工具。
        #   - 遍历 skill.tools,调用 self.registry.register(schema.name, func, schema);
        #     遇到重名给出清晰错误。
        #   - self.skills.append(skill)
        raise NotImplementedError

    def run(self, ctx: "RunContext", inputs: dict[str, Any]) -> dict[str, Any]:
        """作为 Stage 的 executor 执行。

        约定实现(agentic loop):
          1. 把 inputs(含 State Store 注入的相关切片)组织成一条 user 消息入 memory。
          2. 循环最多 max_steps 次:
               resp = client.chat(memory.render(), tools=registry.schemas())
               若 resp 含 tool_calls:executor 逐个执行,结果作为 tool 消息回填 memory,继续。
               否则:视为最终回复,跳出循环。
          3. 解析最终回复为结构化 outputs(供 Stage 校验 output_schema)。
        """
        # TODO: 实现上述 agentic loop。
        raise NotImplementedError


from typing import TYPE_CHECKING  # noqa: E402

if TYPE_CHECKING:
    from engine.context import RunContext
