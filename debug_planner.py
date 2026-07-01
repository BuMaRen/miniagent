"""
调试入口：测试 Planner 任务分解 + agent_loop 逐步执行。

用法：
    python debug_planner.py
    python debug_planner.py "在 output 目录下创建一个冒泡排序的 Python 文件"
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from llm.providers.openai.client import OpenAIClient
from llm.data.message import Message
from memory.context import ConversationContext
from planning.planner import Planner
from tools.builtin.fs import fs_tools
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry
from core.loop import agent_loop


def main():
    api_key = "ollama"
    base_url = "http://192.168.50.11:11434/v1"
    model = "qwen3.5:9b"

    client = OpenAIClient(api_key=api_key, base_url=base_url, model=model)

    registry = ToolRegistry()
    for func, schema in fs_tools:
        registry.register(schema.name, func, schema)
    executor = ToolExecutor(registry)
    tools = registry.schemas()

    planner = Planner(llm_client=client, max_steps=6)

    user_input = (
        " ".join(sys.argv[1:])
        if len(sys.argv) > 1
        else (
            "在 output 目录下创建一个 Python 文件，实现快速排序算法，并写一个测试用例验证它。"
        )
    )

    print(f"Model     : {model}")
    print(f"Tools     : {[s.name for s in tools]}")
    print(f"User input: {user_input}")
    print("=" * 60)

    # 生成计划
    plan = planner.plan(user_input)
    print(f"生成了 {len(plan.steps)} 个步骤：\n{plan.format()}")
    print("=" * 60)

    # 每个 step 独立运行一次 agent_loop
    system_prompt = (
        "You are a software development expert. "
        "Use the provided file system tools to complete the given task."
    )

    for step in plan.steps:
        print(f"\n▶ Step {step.index}: {step.description}")
        print("-" * 60)

        step.status = "running"

        ctx = ConversationContext(client, system_prompt=system_prompt)
        ctx.append(Message(role="user", content=step.description))

        try:
            result = agent_loop(client, tools, executor, ctx.messages())
            step.status = "done"
            step.result = result or "completed"
        except Exception as e:
            step.status = "failed"
            step.result = str(e)
            print(f"[ERROR] Step {step.index} failed: {e}")

        print(f"\n{plan.format()}")
        print("=" * 60)

    print(f"\nis_complete: {plan.is_complete()}")


if __name__ == "__main__":
    main()
