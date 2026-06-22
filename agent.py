from typing import Optional

from openai import NOT_GIVEN, OpenAI
from tools.mux import tools_mux
from tools import default_tools
from planner import Planner
from state import AgentState

class Agent:
    
    def __init__(self, base_url, api_key, system_prompt=""):
        # 创建 OpenAI 客户端实例，连接 Ollama 服务。
        self.client = OpenAI(base_url=base_url, api_key=api_key)
        # 注册工具到 mux，构建工具调用的单一入口。
        mux = tools_mux()
        for func_name, func in default_tools:
            mux.install_tool(func_name, func)
        self.mux = mux
        # 设置 model 设定的系统提示词
        self.messages = []
        if system_prompt:
            self.messages = [{"role": "system", "content": system_prompt}]
        # 创建 AgentState 实例，管理对话状态和生命周期。
        self.state = AgentState()
        # 创建 Planner 实例
        self.planner = Planner(self.client, max_steps=5)

    @property
    def tools(self):
        return self.mux.tools
    
    def install_tool(self, function_name, function):
        self.mux.install_tool(function_name, function)
    
    def call_tool(self, tool_call):
        function_name = tool_call.function.name
        arguments = tool_call.function.arguments
        return self.mux.call(function_name, arguments)

    def _format_plan(self, steps: list[str]) -> str:
        if not steps:
            return ""
        lines = ["执行计划："]
        for idx, step in enumerate(steps, start=1):
            lines.append(f"{idx}. {step}")
        return "\n".join(lines)

    def _build_user_message(self, content: str) -> str:
        """总结过往对话回答（有的话）和当前规划结果+用户消息内容。
        """
        blocks = []
        # 获取过往轮次的状态摘要（主要是上一轮回答）
        state_summary = self.state.summary_for_user()
        if state_summary:
            blocks.append(state_summary)

        # 将规划好的步骤转化为文本注入，供模型参考执行
        plan_text = self._format_plan(self.state.current_plan)
        if plan_text:
            blocks.append(plan_text)

        # 有用户输入
        if content:
            blocks.append(f"用户任务：{content}")
        return "\n\n".join(blocks)
    
    def user_prompt(self, model, content, tools=NOT_GIVEN):
        # Phase 1: content 非空的情况表示用户输入了文本，需要任务规划
        if content:
            # 创建 state 记录任务状态
            self.state.start_turn()
            # 从 state 中获取状态摘要（当前只有上一轮回答）
            state_summary = self.state.summary_for_user()
            # 向 model 发起调用，请求任务步骤分解
            plan_steps = self.planner.plan(model=model, user_input=content, state_summary=state_summary)
            # 记录任务分解后的步骤记录到 state 中
            self.state.set_plan(plan_steps)

        # Phase 2: 调用层次过深，主动终止对话
        if self.state.depth > 6:
            print("对话过深，终止交互。")
            self.state.depth = 0
            return

        # Phase 3: content 非空时才将用户输入和状态摘要注入 messages，触发模型调用。
        if content:
            self.messages.append({"role": "user", "content": self._build_user_message(content)})

        # Phase 4: 发起 model 调用，没有 content 的情况下，messages 在过往调用中拼接
        response = self.client.chat.completions.create(
            model=model,
            messages=self.messages,
            tools=tools,
            tool_choice="auto" if tools is not NOT_GIVEN else NOT_GIVEN
        )
        assistant_message = response.choices[0].message
        print(f"模型返回了消息，内容是：{assistant_message.content}，工具调用请求是：{', '.join([tool_call.function.name for tool_call in assistant_message.tool_calls]) if assistant_message.tool_calls else '无'}。")
        self.state.depth += 1

        # Phase 5A: model 没有发起工具调用请求
        if not assistant_message.tool_calls:
            print(assistant_message.content)
            # 所有工具调用完成，记录模型返回的答案
            self.messages.append({"role": "assistant", "content": assistant_message.content})
            # 记录最终答案
            self.state.finish_turn(assistant_message.content or "")
            print("本轮结束。")
            return

        print(f"模型调用了工具：{', '.join([tool_call.function.name for tool_call in assistant_message.tool_calls])}。")

        # 将 model 发起的工具调用请求记录到 messages 中，供后续工具调用结果注入上下文时参考。
        self.messages.append(
            {
                "role": "assistant",
                "content": assistant_message.content,
                "tool_calls": [tool_call.model_dump() for tool_call in assistant_message.tool_calls] if assistant_message.tool_calls else []
            }
        )

        # Phase 5B: model 发起了工具调用请求，依次执行工具调用，记录结果到 state 和 messages 中，并再次调用 user_prompt 进入下一轮对话。
        if assistant_message.tool_calls:
            for tool_call in assistant_message.tool_calls:
                # 调用工具并记录道 state 和 messages 中
                tool_response = self.call_tool(tool_call)
                self.state.record_tool(
                    tool_name=tool_call.function.name,
                    args=tool_call.function.arguments,
                    result=tool_response,
                )
                self.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": tool_response
                    }
                )

        # 工具执行完成后，注入一条 user 消息推动模型继续执行下一步。
        # 不注入时模型默认行为是"输出文字答复"而非继续调用工具。
        self.messages.append({"role": "user", "content": "工具调用已完成，请继续执行下一步，直到完成全部计划。"})
        return self.user_prompt(model=model, content="", tools=tools)
