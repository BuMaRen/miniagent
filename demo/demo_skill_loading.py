"""
展示新的 Skill 系统：Skill = Tools + System Prompt + Metadata

这个示例演示了 Skill 的完整定义：
- Skill 不仅仅是工具列表
- Skill 包含：tools + system_prompt + metadata + examples
- 这使得 Skill 成为一个完整的能力包，而非简单的工具集合

对比：
- Tools: 只是函数，没有上下文
- Skill: Tools + 角色定义 + 工作流程 + 最佳实践 + 示例

用法：
    python demo_skill_loading.py
"""

import os
import sys
import io

# 修复 Windows 控制台编码
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from llm.providers.openai.client import OpenAIClient
from core.agent import BaseAgent
from tools.registry import ToolRegistry
from tools.executor import ToolExecutor
from memory.context import ConversationContext
from skills.code_reviewer import code_reviewer_skill


def main():
    print("=" * 60)
    print("   新的 Skill 系统演示")
    print("=" * 60)
    print()

    # 1. 查看 Skill 的完整定义
    print("📦 Skill 完整定义")
    print("-" * 60)
    print(f"名称: {code_reviewer_skill.name}")
    print(f"显示名称: {code_reviewer_skill.display_name}")
    print(f"描述: {code_reviewer_skill.metadata.description}")
    print(f"版本: {code_reviewer_skill.metadata.version}")
    print(f"标签: {', '.join(code_reviewer_skill.metadata.tags)}")
    print(f"工具数量: {len(code_reviewer_skill.tools)}")
    print(f"示例数量: {len(code_reviewer_skill.examples)}")
    print()

    print("🛠️  包含的工具:")
    for func, schema in code_reviewer_skill.tools:
        print(f"  - {schema.name}: {schema.description[:50]}...")
    print()

    print("💡 System Prompt (前300字符):")
    print(code_reviewer_skill.system_prompt[:300] + "...")
    print()

    print("📚 Few-shot 示例:")
    for i, example in enumerate(code_reviewer_skill.examples, 1):
        print(f"  示例 {i}: {example['user'][:40]}...")
    print()

    print("=" * 60)
    print("   Skill vs Tools 对比")
    print("=" * 60)
    print()

    print("❌ 旧设计 (Tools):")
    print("   - 只有工具列表: [(func, schema), ...]")
    print("   - 没有角色定义和工作流程")
    print("   - System prompt 需要单独管理")
    print("   - 使用者需要自己理解如何使用这些工具")
    print()

    print("✅ 新设计 (Skill):")
    print("   - 工具 + System Prompt + Metadata + Examples")
    print("   - 包含角色定义、工作流程、最佳实践")
    print("   - 自动注入 system prompt 到 Agent")
    print("   - 提供 Few-shot 示例指导 LLM")
    print("   - Skill 是一个完整的能力包")
    print()

    # 2. 创建 LLM 客户端
    api_key = os.getenv("OPENAI_API_KEY", "ollama")
    base_url = os.getenv("OPENAI_BASE_URL", "http://localhost:11434/v1")
    model = os.getenv("OPENAI_MODEL", "gemma4:e2b")

    print("=" * 60)
    print("   加载 Skill 到 Agent")
    print("=" * 60)
    print()

    print(f"🤖 模型: {model}")
    print(f"🔗 地址: {base_url}")
    print()

    client = OpenAIClient(api_key=api_key, base_url=base_url, model=model)

    # 3. 创建基础组件
    print("📦 创建基础组件...")
    registry = ToolRegistry()
    executor = ToolExecutor(registry)
    memory = ConversationContext(client, system_prompt="")  # system_prompt 由 Skill 提供

    # 4. 创建 Agent
    print("🤖 创建 Agent...")
    agent = BaseAgent(
        llm_client=client,
        tool_registry=registry,
        tool_executor=executor,
        memory=memory,
        planner=None,
        agent_state=None
    )

    # 5. 加载 Skill（关键！）
    print()
    print("🎯 加载 Code Reviewer Skill...")
    agent.load_skill(code_reviewer_skill)
    print()

    # 6. 验证 system prompt 已更新
    print("📝 验证 System Prompt 已自动注入:")
    print(f"   当前 system prompt 长度: {len(memory.system_prompt)} 字符")
    print(f"   前100字符: {memory.system_prompt[:100]}...")
    print()

    # 7. 查看已加载的工具
    print("📋 已加载的工具：")
    for schema in registry.schemas():
        print(f"  - {schema.name}")
    print()

    print("=" * 60)
    print("   总结")
    print("=" * 60)
    print()

    print("🎯 Skill 系统的核心价值:")
    print()
    print("1. ✅ 完整性: Tools + Context (system prompt + examples)")
    print("2. ✅ 封装性: 角色定义、工作流程、最佳实践打包在一起")
    print("3. ✅ 可发现性: Metadata 让 Skill 易于查找和管理")
    print("4. ✅ 可组合性: 一个 Agent 可以加载多个 Skills")
    print("5. ✅ 指导性: Few-shot examples 指导 LLM 正确使用工具")
    print()

    print("💡 Skill ≠ Tools:")
    print("   - Tools: 功能单元（函数）")
    print("   - Skill: 能力包（函数 + 使用指南 + 角色定义）")
    print()

    print("=" * 60)
    print("✅ 演示完成！")
    print()
    print("下一步: 创建更多 Skills")
    print("  - web_scraping_skill")
    print("  - data_analysis_skill")
    print("  - file_management_skill")
    print("=" * 60)


if __name__ == "__main__":
    main()
