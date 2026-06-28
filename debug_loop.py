"""
调试入口：测试 agent_loop + fs 工具。

用法：
    OPENAI_API_KEY=sk-...  python debug_loop.py
    OPENAI_API_KEY=sk-...  python debug_loop.py "列出当前目录下的 Python 文件"

环境变量：
    OPENAI_API_KEY   必填
    OPENAI_BASE_URL  可选，Ollama / 代理等兼容接口
    OPENAI_MODEL     可选，默认 gpt-4o-mini
"""

import os
import sys

from memory.context import ConversationContext

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from llm.providers.openai.client import OpenAIClient
from llm.data.message import Message
from tools.registry import ToolRegistry
from tools.executor import ToolExecutor
from tools.builtin.fs import fs_tools
from core.loop import agent_loop


def main():
    api_key = "ollama"
    base_url = "http://192.168.50.11:11434/v1"
    model = "qwen3:14b"
    
    

    if not api_key:
        print("Error: OPENAI_API_KEY is not set.")
        sys.exit(1)

    client = OpenAIClient(api_key=api_key, base_url=base_url, model=model)

    registry = ToolRegistry()
    for func, schema in fs_tools:
        registry.register(schema.name, func, schema)
    executor = ToolExecutor(registry)

    prompt = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else (
        f"Create a Python file in the {os.getcwd()}/output directory and implement a merge sort algorithm in it."
    )
    print(f"Model   : {model}")
    print(f"Tools   : {[s.name for s in registry.schemas()]}")
    print(f"Prompt  : {prompt}")
    print("-" * 60)

    ctx = ConversationContext(client, system_prompt="You are a software development expert. Use the provided file system tools to write content to the file system whenever necessary.")
    
    ctx.append(Message(role="user", content=prompt))
    agent_loop(client, registry.schemas(), executor, ctx)


if __name__ == "__main__":
    print("Debug loop starting...")
    main()
    print("Debug loop finished.")
