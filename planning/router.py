from llm import LLMClient, Message

import json

router_prompt = """你是一个系统底层的意图路由引擎（Router）。
你的唯一任务是：分析用户的输入，并判断是否需要规划。

【输出格式】
严格输出 JSON，格式如下：
{
  "need_plan": false,
  "reason": "一句话解释为什么需要或不需要规划"
}

【示例】
输入：帮我对比一下苹果和微软的财报，然后写一封总结邮件发给老板。
输出：{"need_plan": true, "reason": "这是一个包含对比分析和发邮件的多步复杂任务"}

输入：计算1+1的和？
输出：{"need_plan": false, "reason": "这是简单的数学计算任务，无需规划"}

【严格规则】
1. 你的回答必须以'{'开始，以'}'结束，严格遵循 JSON 格式。
2. need_plan 的值必须是 true 或 false。"""


# 小模型服从性差，需要额外处理json
class Router:
    """Router is responsible for determining whether a user's input requires a plan.

    Attributes:
        llm_client (LLMClient): The LLM client used for processing user input.
    Methods:
        need_plan(user_input: str) -> bool: Determines if the input requires planning.
    """

    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client

    def need_plan(self, user_input):
        """Determine if the user's input requires a plan.

        Args:
            user_input (str): The user's input message.

        Returns:
            bool: True if the input requires planning, False otherwise.
        """
        response = self.llm_client.chat(
            [
                Message(role="system", content=router_prompt),
                Message(role="user", content=user_input),
            ], None
        )
        print(f"Router response: {response.message.content}")
        content = response.message.content
        if content.startswith("```json"):
            content = content[7:-3]        
        try:
            body = json.loads(content)
            return True if body.get("need_plan", False) else False
        except Exception as e:
            print(f"Error parsing response: {e}")
            return False
