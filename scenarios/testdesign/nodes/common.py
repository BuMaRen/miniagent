from llm.client import LLMClient
from agent import ToolSet, Agent, ConversationMemory
from tools.registry import ToolRegistry, tool


@tool
def read_file(path: str) -> str:
    """读取文件内容,返回 str

    Args:
        path (str): 文件路径
    """
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


@tool
def find_file(filename: str, search_paths: list[str]) -> str:
    """在指定路径列表中查找文件,返回第一个找到的文件路径,找不到时返回错误信息

    Args:
        filename (str): 文件名
        search_paths (list[str]): 搜索路径列表
    """
    import os

    for path in search_paths:
        full_path = os.path.join(path, filename)
        if os.path.isfile(full_path):
            return full_path
    return f"file not found in search paths: {search_paths}"


@tool
def pwd() -> str:
    """返回当前工作目录"""
    import os

    return os.getcwd()


def make_agent(
    client: LLMClient,
    toolset: ToolSet,
    system_prompt: str,
    max_steps: int = 12,
    output_schema=None,
) -> Agent:
    agent = Agent(
        client=client,
        memory=ConversationMemory(),
        system_prompt=system_prompt,
        registry=ToolRegistry(),
        max_steps=max_steps,
        output_schema=output_schema,
    )
    for tool in toolset:
        agent.load_toolset(tool)
    return agent
