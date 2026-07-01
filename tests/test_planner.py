import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.pkg.planner import TestPlanner
from llm import OpenAIClient
from memory.context import ConversationContext
from tools.registry import ToolRegistry
from tools.executor import ToolExecutor
from tools.builtin import fs_tools
from core.agent import BaseAgent
from planning import Router, Planner
from state import AgentRuntime



base_url = "http://192.168.50.11:11434/v1"
api_key = "ollama"
planner_model = "qwen3.6:35b-a3b"
main_model = "qwen3.5:9b"

tools_registry = ToolRegistry()
for tool in fs_tools:
    tools_registry.register(tool[1].name, tool[0], tool[1])
tools_executor = ToolExecutor(tools_registry)

sysytem_prompt = (
    "你是一个分布式系统设计专家，擅长设计并指导落地各种复杂系统。"
    "你需要根据用户的需求或者目标，设计出一个可落地的系统方案。"
    "你需要给出包含设计思路、原理解析、方案和技术选型以及落地方案。"
    "在完成设计方案后，你需要将设计方案整理成一份markdown文档，包含尽可能多的设计细节。"
)
main_client = OpenAIClient(api_key=api_key, base_url=base_url, model=main_model)
memory = ConversationContext(
    client=main_client,
    system_prompt=sysytem_prompt,
    threshold=20,
)
router = Router(llm_client=main_client)
agent_state = AgentRuntime()

main_agent = BaseAgent(
    llm_client=main_client,
    tool_registry=tools_registry,
    tool_executor=tools_executor,
    memory=memory,
    router=router,
    planner=TestPlanner(),
    agent_state=agent_state
)

main_agent.run("设计一个简易的service mesh，英文回答")
main_agent.run("将设计好的内容整理成一份markdown文档，包含尽可能多的设计细节，存放到D:\\projects\\github.com\\BuMaRen\\miniagent\\output目录中")
