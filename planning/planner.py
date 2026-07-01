# Planner：将用户输入拆解为可执行的步骤列表。
#
# 功能：
#   - plan(user_input: str, context: str | None) -> Plan
#       调用 LLM，将 user_input 分解为若干有序步骤，返回 Plan 对象
#
# Prompt 设计要点：
#   - 让 LLM 以 JSON 格式返回步骤列表，便于结构化解析
#   - 注入 context（如上一轮答案摘要）帮助 LLM 了解当前状态
#   - 步骤数量有上限（从 AgentConfig.max_steps 读取）
#
# 可选功能 replan(plan, failed_step, error) -> Plan：
#   - 当某步骤失败时，根据失败原因重新规划剩余步骤
#
# 注意：
#   - Planner 使用的 LLM 调用是独立的（不影响 agentic loop 的 messages 列表）

import json

from llm.base.client import LLMClient
from llm.data.message import LLMResponse, Message
from tools.schema import ToolSchema

from .step import Plan, Step

planner_prompt = """你是一个任务规划器，将用户输入拆解为可执行的步骤列表。
你的唯一任务是：分析用户的输入，将复杂任务分解成若干有序步骤。
你的回答必须以'{'开始，以'}'结束，严格遵循 JSON 格式。

【输出格式】
严格输出 JSON，格式如下：
{
  "steps": [
    "步骤1",
    "步骤2",
    ...
  ]
}

【示例】
输入：帮我对比一下苹果和微软的财报，然后写一封总结邮件发给老板。
输出：{"steps": ["步骤1", "步骤2", ...]}

输入：计算1+1的和？
输出：{"steps": ["简单问题无需规划，只返回一个步骤"]}
"""


class Planner:
    """Planner is responsible for breaking down user input into executable steps.

    Attributes:
        llm_client (LLMClient): The LLM client used for processing user input.
        max_steps (int): The maximum number of steps allowed in a plan.
    Methods:
        plan(user_input: str, context: str | None = None, tools: list[ToolSchema] | None = None) -> Plan: Breaks down user input into a plan.
    """

    def __init__(self, llm_client: LLMClient, max_steps=10):
        self.llm_client = llm_client
        self.max_steps = max_steps

    def plan(
        self,
        user_input: str,
        context: str | None = None,
        tools: list[ToolSchema] | None = None,
    ) -> Plan:
        """Break down user input into a plan.

        Args:
            user_input (str): The user's input message.
            context (str | None, optional): Additional context for planning. Defaults to None.
            tools (list[ToolSchema] | None, optional): Tools available for planning. Defaults to None.

        Raises:
            ValueError: If the LLM response is not valid JSON.

        Returns:
            Plan: The generated plan.
        """
        system_prompt = planner_prompt + f"\n【限制】\n步骤数量不超过 {self.max_steps}\n"
        messages = []
        messages.append(Message(role="system", content=system_prompt))

        user_prompt = f"请分析规划用户输入: {user_input}"
        if context:
            user_prompt += f"\n可参考的上下文: {context}"
        messages.append(Message(role="user", content=user_prompt))

        response: LLMResponse = self.llm_client.chat(messages, tools=tools)
        response_content = response.message.content

        try:
            steps = json.loads(response_content)  # 验证 JSON 格式
            steps_list = []
            index = 1
            for step in steps.get("steps", []):
                steps_list.append(Step(index=index, description=step, status="pending"))
                index += 1

            return Plan(steps=steps_list, current_index=0)
        except json.JSONDecodeError:
            raise ValueError(f"LLM 返回的步骤不是有效的 JSON 格式: {response_content}")
