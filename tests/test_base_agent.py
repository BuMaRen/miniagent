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
summary_model = "gemma4:e2b"

sysytem_prompt = """Your Role: You are a kubernetes expert.
Your Job: You will help the user to solve their kubernetes problems.
Your Capabilities: You can use available tools to provide guidance, troubleshooting steps, and best practices for Kubernetes. You can also suggest tools and resources to help the user with their Kubernetes issues.
"""

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

main_agent.run("What is Deployment?")
main_agent.run("how pvc and pv work in it?")
