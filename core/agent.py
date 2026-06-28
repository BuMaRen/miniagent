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
        planner,
        agent_state,
    ):
        self.llm_client = llm_client
        self.tool_registry = tool_registry
        self.tool_executor = tool_executor
        self.memory = memory
        self.planner = planner
        self.agent_state = agent_state

    def run(self, user_input: str):
        self.memory.append(Message(role="user", content=user_input))
        agent_loop(
            self.llm_client,
            self.tool_registry.schemas(),
            self.tool_executor,
            self.memory
        )

    def install_tool(self, name: str, func):
        # 动态注册工具
        self.tool_registry.register(name, func)

    def on_before_tool(self, tool_name: str):
        # 可选重写的 hook，在工具执行前调用
        pass

    def on_after_tool(self, tool_name: str):
        # 可选重写的 hook，在工具执行后调用
        pass
