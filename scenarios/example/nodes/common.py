from bumaren_agent_workflow.llm.client import LLMClient
from bumaren_agent_workflow.agent import ToolSet, Agent, ConversationMemory
from bumaren_agent_workflow.tools.registry import ToolRegistry


def make_agent(
    client: LLMClient,
    system_prompt: str,
    toolsets: tuple[ToolSet, ...] = (),
    max_steps: int = 12,
    output_schema=None,
) -> Agent:
    agent = Agent(
        client=client,
        memory=ConversationMemory(system_prompt=system_prompt),
        registry=ToolRegistry(),
        max_steps=max_steps,
        output_schema=output_schema,
    )
    for toolset in toolsets:
        agent.load_toolset(toolset)
    return agent
