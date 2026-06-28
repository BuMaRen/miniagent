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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from llm.providers.openai.client import OpenAIClient
from llm.data.message import Message
from tools.registry import ToolRegistry
from tools.executor import ToolExecutor
from tools.builtin.fs import fs_tools
from core.loop import agent_loop


def main():
    # api_key = os.environ.get("OPENAI_API_KEY", "")
    # base_url = os.environ.get("OPENAI_BASE_URL") or None
    # model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    api_key = "ollama"
    base_url = "http://localhost:11434/v1"
    model = "qwen3.5:2b"

    if not api_key:
        print("Error: OPENAI_API_KEY is not set.")
        sys.exit(1)

    client = OpenAIClient(api_key=api_key, base_url=base_url)
    client.messages.append(Message(
        role="system",
        content="You are a helpful assistant. Use the provided file system tools to answer the user's question.",
    ))

    registry = ToolRegistry()
    for func, schema in fs_tools:
        registry.register(schema.name, func, schema)

    executor = ToolExecutor(registry)

    prompt = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else (
        f"请列出 {os.getcwd()} 目录下的内容，判断是否有名为 main.py 的文件。"
    )

    print(f"Model   : {model}")
    print(f"Tools   : {[s.name for s in registry.schemas()]}")
    print(f"Prompt  : {prompt}")
    print("-" * 60)

    agent_loop(client, prompt, registry.schemas(), executor, model=model)


if __name__ == "__main__":
    print("Debug loop starting...")
    main()
    print("Debug loop finished.")
