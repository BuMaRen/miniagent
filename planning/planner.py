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


class Planner:
    def __init__(self, llm_client: LLMClient, max_steps=10):
        self.llm_client = llm_client
        self.max_steps = max_steps

    def plan(
        self,
        user_input: str,
        context: str | None = None,
        tools: list[ToolSchema] | None = None,
    ) -> Plan:
        planner_prompt = (
            "你是一个任务规划器，将用户输入拆解为可执行的步骤列表。\n"
            "要求：\n"
            "1. 必须以 JSON 格式返回步骤列表\n"
            '2. 格式为\'{"steps": ["step1", "step2", ...]}\'\n'
            f"3. 步骤数量不超过 {self.max_steps}\n"
            # "4. 如果任务并不复杂，返回用户输入作为一个步骤\n"
        )
        messages = []
        messages.append(Message(role="system", content=planner_prompt))

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

            return Plan(steps=steps_list, current_index=1)
        except json.JSONDecodeError:
            raise ValueError(f"LLM 返回的步骤不是有效的 JSON 格式: {response_content}")
