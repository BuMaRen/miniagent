"""
Code Reviewer Skill 使用示例。

演示两种使用方式：
1. 使用辅助函数创建预配置的 Agent
2. 手动创建 Agent 并加载 Skill

用法：
    # 1. 审查单个文件
    python example_code_reviewer.py --file path/to/file.py

    # 2. 审查整个目录
    python example_code_reviewer.py --directory ./core

    # 3. 快速安全检查
    python example_code_reviewer.py --file path/to/file.py --quick security

环境变量：
    OPENAI_API_KEY   必填（或使用 Ollama 等兼容接口）
    OPENAI_BASE_URL  可选，默认 OpenAI 官方 API
    OPENAI_MODEL     可选，默认 gpt-4o-mini
"""

import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from llm.providers.openai.client import OpenAIClient
from skills.code_reviewer import create_code_reviewer_agent


def main():
    parser = argparse.ArgumentParser(description="代码审查工具")
    parser.add_argument("--file", type=str, help="要审查的文件路径")
    parser.add_argument("--directory", type=str, help="要审查的目录路径")
    parser.add_argument("--pattern", type=str, default="*.py", help="文件匹配模式（仅用于目录审查）")
    parser.add_argument("--quick", type=str, choices=["security", "complexity", "style"],
                        help="快速检查模式（security/complexity/style）")
    args = parser.parse_args()

    # 读取配置
    api_key = os.getenv("OPENAI_API_KEY", "ollama")
    base_url = os.getenv("OPENAI_BASE_URL", "http://localhost:11434/v1")
    model = os.getenv("OPENAI_MODEL", "gemma4:e2b")

    if not api_key:
        print("Error: OPENAI_API_KEY 环境变量未设置")
        sys.exit(1)

    # 创建 LLM 客户端
    print(f"🤖 使用模型: {model}")
    print(f"🔗 API 地址: {base_url}")
    print("-" * 60)

    client = OpenAIClient(api_key=api_key, base_url=base_url, model=model)

    # 方式1: 使用辅助函数创建预配置的 Code Reviewer Agent
    agent = create_code_reviewer_agent(client)

    # 方式2 (备选): 手动创建 Agent 并加载 Skill
    # from core.agent import BaseAgent
    # from tools.registry import ToolRegistry
    # from tools.executor import ToolExecutor
    # from memory.context import ConversationContext
    # from skills.code_reviewer import code_reviewer_skill, CODE_REVIEWER_SYSTEM_PROMPT
    #
    # registry = ToolRegistry()
    # executor = ToolExecutor(registry)
    # memory = ConversationContext(client, system_prompt=CODE_REVIEWER_SYSTEM_PROMPT)
    # agent = BaseAgent(client, registry, executor, memory, None, None)
    # agent.load_skill(code_reviewer_skill)

    # 执行审查任务
    if args.quick and args.file:
        # 快速检查模式
        print(f"🔍 快速 {args.quick} 检查: {args.file}")

        check_tools = {
            "security": "check_security_issues",
            "complexity": "analyze_code_complexity",
            "style": "check_code_style"
        }

        prompt = f"""请快速检查文件 '{args.file}' 的 {args.quick} 问题：

1. 使用 read_file 读取文件
2. 使用 {check_tools[args.quick]} 进行检查
3. 总结检查结果"""

        agent.run(prompt)

    elif args.file:
        # 单文件审查
        print(f"📝 审查文件: {args.file}")

        prompt = f"""请审查以下 Python 代码文件：{args.file}

执行步骤：
1. 使用 read_file 读取文件内容
2. 使用 analyze_code_complexity 分析复杂度
3. 使用 check_security_issues 检查安全问题
4. 使用 check_code_style 检查代码风格
5. 使用 generate_review_report 生成完整报告

请按顺序调用这些工具，并在最后返回生成的审查报告。"""

        agent.run(prompt)

    elif args.directory:
        # 目录审查
        print(f"📁 审查目录: {args.directory}")
        print(f"🔍 匹配模式: {args.pattern}")

        prompt = f"""请审查目录 '{args.directory}' 下所有匹配 '{args.pattern}' 的文件：

执行步骤：
1. 使用 search_files 查找所有匹配的文件
2. 对每个文件依次进行审查：
   - read_file 读取内容
   - analyze_code_complexity 分析复杂度
   - check_security_issues 检查安全问题
   - check_code_style 检查风格
   - generate_review_report 生成报告
3. 汇总所有文件的审查结果"""

        agent.run(prompt)

    else:
        print("Error: 请指定 --file 或 --directory")
        parser.print_help()
        sys.exit(1)

    print("-" * 60)
    print("✅ 代码审查完成！")


if __name__ == "__main__":
    main()
