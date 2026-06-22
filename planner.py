import json

class Planner:
    """能力：
    1. 无状态调用
    2. 结构化输出
    3. 失败不崩溃
    4. 步骤数量上限
    """
    def __init__(self, client, max_steps=5):
        self.client = client
        self.max_steps = max_steps
    
    def plan(self, model, user_input, state_summary)->list[str]:
        prompt = (
            "你是任务规划器。"
            f"请把用户任务拆解为可执行步骤，最多{self.max_steps}步。"
            "仅输出JSON，格式：{\"steps\": [\"step1\", \"step2\"]}。"
        )
        if state_summary:
            prompt += f"\n历史状态摘要：{state_summary}\n请在规划时考虑这些历史信息。"
        system_prompt = {
            "role": "system",
            "content": prompt
        }
        user_prompt = {
            "role": "user",
            "content": user_input
        }
        
        response = self.client.chat.completions.create(
            model=model,
            messages=[system_prompt, user_prompt],
            temperature=0
        )
        content = response.choices[0].message.content or ""

        try:
            result = json.loads(content)
            steps = result.get("steps", [])
            if not isinstance(steps, list):
                return [user_input]
            return [str(step) for step in steps[: self.max_steps]] or [user_input]
        except json.JSONDecodeError:
            return [user_input]
