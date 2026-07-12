# Agent 基类，框架使用者继承此类来创建自己的 Agent。
#
# 职责：
#   - 持有 LLMClient、ToolRegistry、Memory、Planner、AgentState 等核心组件的引用
#   - 提供 run(user_input: str) 公共入口，内部委托给 AgentLoop 执行
#   - 提供 install_tool(name, func) 方法，允许动态注册工具
#   - 提供 on_before_tool / on_after_tool hook 扩展点（可选重写）
#
# 不应包含：
#   - 任何与具体 LLM provider 耦合的代码
#   - loop 控制流逻辑（放在 loop.py）
#   - 工具执行逻辑（放在 tools/executor.py）

from llm.base.client import LLMClient
from llm.data.message import Message
from planning import Router, Planner
from state import AgentRuntime
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry

from memory import ConversationContext

from .loop import agent_loop


class BaseAgent:
    def __init__(
        self,
        llm_client: LLMClient,
        tool_registry: ToolRegistry,
        tool_executor: ToolExecutor,
        memory: ConversationContext,
        router: Router,
        planner: Planner,
        agent_state: AgentRuntime,
    ):
        self.llm_client = llm_client
        self.tool_registry = tool_registry
        self.tool_executor = tool_executor
        self.memory = memory
        self.router = router
        self.planner = planner
        self.state = agent_state

    def run(self, user_input: str):
        if not self.router or not self.planner or not self.router.need_plan(user_input):
            lines = [line for line in user_input.splitlines() if line.strip()]
            if len(lines) <= 1:
                self.memory.append(Message(role="user", content=user_input))
                answer = agent_loop(
                    self.llm_client,
                    self.tool_registry.schemas(),
                    self.tool_executor,
                    self.memory.messages(),
                )
                self.memory.append(Message(role="assistant", content=answer))
                return answer

            # 多行输入：每一行单独发起一次 chat，每次都是独立的上下文（不携带
            # 其他行的解析结果/工具调用记录），只共享同一个 uuid。过程中的
            # 每次 chat 都不打印，等 run 整体结束后统一由调用方打印最终结果。
            system_msg = self.memory.messages()[0]
            tools = self.tool_registry.schemas()

            uuid_messages = [
                system_msg,
                Message(
                    role="user",
                    content="请调用 id_generate 工具生成一个唯一的订单编号。",
                ),
            ]
            agent_loop(
                self.llm_client, tools, self.tool_executor, uuid_messages, verbose=False
            )
            order_uuid = next(
                (m.content for m in uuid_messages if m.role == "tool"), ""
            )

            for line in lines:
                line_messages = [
                    system_msg,
                    Message(
                        role="user",
                        content=(
                            f"订单编号（uuid）为：{order_uuid}\n"
                            f"请解析以下这一行内容，并使用该订单编号调用 record 工具记录解析结果：\n{line}"
                        ),
                    ),
                ]
                agent_loop(
                    self.llm_client, tools, self.tool_executor, line_messages, verbose=False
                )

            summary_messages = [
                system_msg,
                Message(
                    role="user",
                    content=(
                        f"所有行已处理完毕，请使用订单编号 {order_uuid} 调用 "
                        "summary_record 工具生成最终汇总结果并返回给用户。"
                    ),
                ),
            ]
            answer = agent_loop(
                self.llm_client, tools, self.tool_executor, summary_messages, verbose=False
            )

            self.memory.append(Message(role="user", content=user_input))
            self.memory.append(Message(role="assistant", content=answer))
            return answer
        sts = self.state
        sts.reset()
        sts.plan = self.planner.plan(user_input, self.memory.context())
        self.memory.append(Message(role="user", content=user_input))

        messages = self.memory.messages()

        while not sts.plan.is_complete() and sts.plan.current_step():
            step = sts.plan.current_step()
            user_input = step.description
            messages.append(
                Message(role="system", content=f"Step {step.index}: {user_input}")
            )
            answer = agent_loop(
                self.llm_client,
                self.tool_registry.schemas(),
                self.tool_executor,
                messages,
                state=sts,
            )
            messages.append(Message(role="assistant", content=answer))
            sts.plan.advance(answer)

        summary = sts.summary()

    def install_tool(self, name: str, func):
        # 动态注册工具
        self.tool_registry.register(name, func)

    def on_before_tool(self, tool_name: str):
        # 可选重写的 hook，在工具执行前调用
        pass

    def on_after_tool(self, tool_name: str):
        # 可选重写的 hook，在工具执行后调用
        pass
