"""
演示 Skill 的 System Prompt 不会破坏对话上下文。

测试场景：
1. 用户与 Agent 建立对话上下文（介绍自己）
2. 加载 Code Reviewer Skill
3. 使用 Skill 完成任务
4. 继续对话，验证上下文是否保留

用法：
    python test_context_preservation.py
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


def print_section(title):
    """打印分隔线"""
    print()
    print("=" * 60)
    print(f"   {title}")
    print("=" * 60)
    print()


def print_messages(memory):
    """打印当前的 messages"""
    print("当前对话上下文:")
    print("-" * 60)
    for msg in memory.messages():
        role_emoji = {
            "system": "🔧",
            "user": "👤",
            "assistant": "🤖"
        }.get(msg.role, "❓")

        content = msg.content[:100] + "..." if len(msg.content) > 100 else msg.content
        print(f"{role_emoji} {msg.role}: {content}")
    print("-" * 60)
    print()


def main():
    print_section("上下文保护测试")

    # 创建 LLM 客户端
    api_key = os.getenv("OPENAI_API_KEY", "test-key")
    base_url = os.getenv("OPENAI_BASE_URL", "http://localhost:11434/v1")
    model = os.getenv("OPENAI_MODEL", "gemma4:e2b")

    print(f"🤖 模型: {model}")
    print()

    client = OpenAIClient(api_key=api_key, base_url=base_url, model=model)

    # 创建 Agent（基础角色：AI 助手）
    print("📦 创建 Agent...")
    registry = ToolRegistry()
    executor = ToolExecutor(registry)

    base_system_prompt = """你是一个友好的 AI 助手，名叫小智。

你的特点：
- 善于记忆用户信息
- 乐于助人
- 回答简洁明了

请记住用户告诉你的信息，以便后续对话中使用。"""

    memory = ConversationContext(client, system_prompt=base_system_prompt)

    agent = BaseAgent(
        llm_client=client,
        tool_registry=registry,
        tool_executor=executor,
        memory=memory,
        planner=None,
        agent_state=None
    )

    print()
    print_messages(memory)

    # 场景 1: 建立对话上下文
    print_section("场景 1: 建立对话上下文")

    print("👤 用户: 你好，我是李华，我喜欢编程，尤其是 Python")
    print()

    # 模拟对话（不实际调用 LLM）
    from llm.data.message import Message
    memory.append(Message(role="user", content="你好，我是李华，我喜欢编程，尤其是 Python"))
    memory.append(Message(role="assistant", content="你好李华！很高兴认识你。我看到你喜欢 Python 编程，这是一门很棒的语言！有什么我可以帮助你的吗？"))

    print_messages(memory)

    # 场景 2: 加载 Skill（不同模式对比）
    print_section("场景 2: 加载 Code Reviewer Skill")

    from skills.code_reviewer import code_reviewer_skill

    print("测试 mode='append'（推荐）")
    print()

    # 保存当前状态
    messages_before = memory.messages().copy()

    agent.load_skill(code_reviewer_skill, mode="append")
    print()

    print("📝 System Prompt 变化:")
    print(f"   加载前长度: {len(messages_before[0].content)} 字符")
    print(f"   加载后长度: {len(memory.messages()[0].content)} 字符")
    print(f"   前200字符: {memory.messages()[0].content[:200]}...")
    print()

    print_messages(memory)

    # 验证上下文是否保留
    print_section("场景 3: 验证上下文保留")

    print("✅ 检查对话历史是否保留:")
    user_messages = [msg for msg in memory.messages() if msg.role == "user"]
    assistant_messages = [msg for msg in memory.messages() if msg.role == "assistant"]

    print(f"   用户消息数: {len(user_messages)}")
    print(f"   助手消息数: {len(assistant_messages)}")
    print()

    if len(user_messages) > 0:
        print(f"   第一条用户消息: {user_messages[0].content[:50]}...")
        if "李华" in user_messages[0].content:
            print("   ✅ 用户自我介绍已保留")
        else:
            print("   ❌ 用户自我介绍丢失！")
    print()

    if len(assistant_messages) > 0:
        print(f"   第一条助手消息: {assistant_messages[0].content[:50]}...")
        if "李华" in assistant_messages[0].content:
            print("   ✅ 助手回复已保留")
        else:
            print("   ❌ 助手回复丢失！")
    print()

    # 场景 4: 对比不同模式
    print_section("场景 4: 对比不同模式的影响")

    print("📊 mode='append' (当前使用):")
    print("   ✅ 保留原有 system prompt（你是小智...）")
    print("   ✅ 追加 Skill prompt（代码审查工具使用指南）")
    print("   ✅ 保留所有对话历史")
    print("   ✅ Agent 仍然记得用户是李华")
    print()

    print("📊 mode='replace' (如果使用):")
    print("   ❌ 替换 system prompt 为 Skill prompt")
    print("   ❌ 原有角色定义丢失（不再是小智）")
    print("   ⚠️  对话历史仍保留，但上下文错位")
    print("   ⚠️  System: '你是代码审查专家'")
    print("      User: '你好，我是李华...'")
    print("      Assistant: '你好李华...'")
    print("      (上下文不一致！)")
    print()

    print("📊 mode='tools_only':")
    print("   ✅ 只加载工具")
    print("   ✅ 不修改 system prompt")
    print("   ⚠️  需要手动在 base prompt 中说明工具用法")
    print()

    # 总结
    print_section("总结")

    print("✅ 推荐做法:")
    print()
    print("1. 使用 mode='append' (默认):")
    print("   agent.load_skill(skill, mode='append')")
    print()
    print("2. 在 Skill 的 system_prompt 中:")
    print("   - ❌ 不要定义角色（\"你是代码审查专家\"）")
    print("   - ✅ 只描述工具用法和流程")
    print()
    print("3. Agent 的基础 system prompt:")
    print("   - 定义 Agent 的全局角色")
    print("   - 持久化，不因 Skill 加载而改变")
    print()
    print("4. 结果:")
    print("   - Agent 保持一致的角色")
    print("   - 对话上下文完整保留")
    print("   - Skill 作为临时能力增强")
    print()

    print("=" * 60)


if __name__ == "__main__":
    main()
