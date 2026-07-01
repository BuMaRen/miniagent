from llm.providers.openai.client import OpenAIClient
from memory.context import ConversationContext
from tools.registry import ToolRegistry
from tools.executor import ToolExecutor
from tools.builtin import fs_tools
from core.agent import BaseAgent
from planning import Router, Planner
from state import AgentRuntime

base_url = "http://192.168.50.11:11434/v1"
api_key = "ollama"
main_model = "gemma4:e2b"

sysytem_prompt = """你是一个系统底层的意图路由引擎（Router）。
你的唯一任务是：分析用户的输入，并判断是否需要规划，然后仅输出 JSON 格式。

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
1. 只能输出 JSON 对象，不能包含任何 Markdown 标记（如 ```json ），不能有任何解释性文字！
2. need_plan 的值必须是 true 或 false。"""

llm_client = OpenAIClient(api_key=api_key, base_url=base_url, model=main_model)
tools_registry = ToolRegistry()
for tool in fs_tools:
    tools_registry.register(tool[1].name, tool[0], tool[1])
tools_executor = ToolExecutor(tools_registry)
memory = ConversationContext(
    client=llm_client,
    system_prompt=sysytem_prompt,
    threshold=20,
)

router = Router(llm_client=llm_client)
planner = Planner(llm_client=llm_client)
agent_state = AgentRuntime()

main_agent = BaseAgent(
    llm_client=llm_client,
    tool_registry=tools_registry,
    tool_executor=tools_executor,
    memory=memory,
    router=router,
    planner=planner,
    agent_state=agent_state
)

main_agent.run("现在是几点？")
