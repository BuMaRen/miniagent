"""
完整的 Skill 使用示例 - 从零到一。

这个示例展示了如何：
1. 创建一个对话 Agent
2. 与 Agent 正常对话
3. 加载 Code Reviewer Skill
4. 使用 Skill 完成任务
5. 继续对话，验证上下文保留

用法：
    python demo_complete_workflow.py
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
from llm.data.message import Message


def print_separator(title=""):
    """打印分隔线"""
    print()
    print("=" * 60)
    if title:
        print(f"   {title}")
        print("=" * 60)
    print()


def main():
    print_separator("Skill 完整使用流程演示")

    # 配置
    api_key = os.getenv("OPENAI_API_KEY", "test-key")
    base_url = os.getenv("OPENAI_BASE_URL", "http://localhost:11434/v1")
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    print(f"🤖 模型: {model}")
    print()

    # ========================================
    # 步骤 1: 创建对话 Agent
    # ========================================
    print_separator("步骤 1: 创建通用对话 Agent")

    print("创建 LLM 客户端...")
    client = OpenAIClient(api_key=api_key, base_url=base_url, model=model)

    print("创建 Agent 组件...")
    registry = ToolRegistry()
    executor = ToolExecutor(registry)

    # 定义 Agent 的基础角色
    base_system_prompt = """你是一个友好的 AI 助手，名叫小智。

你的特点：
- 善于记忆用户信息
- 乐于助人
- 回答简洁明了

当用户请求特定任务时，你可以使用可用的工具来完成。"""

    memory = ConversationContext(client, system_prompt=base_system_prompt)

    agent = BaseAgent(
        llm_client=client,
        tool_registry=registry,
        tool_executor=executor,
        memory=memory,
        planner=None,
        agent_state=None
    )

    print("✅ Agent 创建完成")
    print(f"   基础角色: AI助手小智")
    print(f"   工具数量: {len(registry.schemas())}")
    print()

    # ========================================
    # 步骤 2: 正常对话
    # ========================================
    print_separator("步骤 2: 与 Agent 正常对话")

    print("👤 用户: 你好，我是张三，我在做一个 Python 项目")
    print()

    # 模拟对话（实际使用时会调用 LLM）
    memory.append(Message(role="user", content="你好，我是张三，我在做一个 Python 项目"))
    memory.append(Message(
        role="assistant",
        content="你好张三！很高兴认识你。听起来你在做 Python 开发，有什么我可以帮助你的吗？"
    ))

    print("🤖 小智: 你好张三！很高兴认识你。听起来你在做 Python 开发，有什么我可以帮助你的吗？")
    print()

    print(f"📊 当前状态:")
    print(f"   对话轮次: {len([m for m in memory.messages() if m.role == 'user'])}")
    print(f"   System prompt 长度: {len(memory.system_prompt)} 字符")
    print()

    # ========================================
    # 步骤 3: 加载 Code Reviewer Skill
    # ========================================
    print_separator("步骤 3: 加载 Code Reviewer Skill")

    from skills.code_reviewer import code_reviewer_skill

    print("📦 Skill 信息:")
    print(f"   名称: {code_reviewer_skill.display_name}")
    print(f"   描述: {code_reviewer_skill.metadata.description[:50]}...")
    print(f"   工具数量: {len(code_reviewer_skill.tools)}")
    print()

    print("加载 Skill (mode='append')...")
    agent.load_skill(code_reviewer_skill, mode="append")
    print()

    print(f"📊 加载后状态:")
    print(f"   工具数量: {len(registry.schemas())} (增加了 {len(code_reviewer_skill.tools)} 个)")
    print(f"   System prompt 长度: {len(memory.system_prompt)} 字符 (追加了工具使用指南)")
    print()

    print("✅ 已加载工具:")
    for schema in registry.schemas():
        print(f"   - {schema.name}")
    print()

    # ========================================
    # 步骤 4: 使用 Skill
    # ========================================
    print_separator("步骤 4: 使用 Skill 完成任务")

    print("👤 用户: 请帮我快速检查 core/loop.py 的安全问题")
    print()

    # 实际使用时，这里会调用 agent.run()
    # 为了演示，我们模拟工具调用
    print("🤖 小智: 好的，我将使用代码审查工具检查安全问题...")
    print()
    print("   [调用工具] read_file(core/loop.py)")
    print("   [调用工具] check_security_issues(...)")
    print()

    # 模拟结果
    memory.append(Message(role="user", content="请帮我快速检查 core/loop.py 的安全问题"))
    memory.append(Message(
        role="assistant",
        content="""好的张三，我已经检查了 core/loop.py 的安全问题：

✅ 未发现明显的安全问题

该文件主要包含 agent_loop 函数，代码结构清晰，没有使用危险函数（eval/exec）或硬编码敏感信息。

需要我进行更详细的代码审查吗？"""
    ))

    print("🤖 小智: 好的张三，我已经检查了 core/loop.py 的安全问题：")
    print()
    print("   ✅ 未发现明显的安全问题")
    print()
    print("   该文件主要包含 agent_loop 函数，代码结构清晰...")
    print()

    # ========================================
    # 步骤 5: 继续对话，验证上下文
    # ========================================
    print_separator("步骤 5: 验证上下文保留")

    print("👤 用户: 我刚才叫什么名字？")
    print()

    memory.append(Message(role="user", content="我刚才叫什么名字？"))
    memory.append(Message(
        role="assistant",
        content="你是张三！我还记得你在做 Python 项目。😊"
    ))

    print("🤖 小智: 你是张三！我还记得你在做 Python 项目。😊")
    print()

    print("✅ 上下文验证:")
    print("   - Agent 仍然记得用户是张三")
    print("   - Agent 仍然记得用户在做 Python 项目")
    print("   - 加载 Skill 没有破坏对话历史")
    print()

    # ========================================
    # 总结
    # ========================================
    print_separator("总结")

    print("📊 完整流程回顾:")
    print()
    print("1. ✅ 创建 Agent (基础角色: 小智)")
    print("2. ✅ 正常对话 (建立上下文: 用户是张三)")
    print("3. ✅ 加载 Skill (mode='append', 追加工具使用指南)")
    print("4. ✅ 使用 Skill (调用代码审查工具)")
    print("5. ✅ 继续对话 (上下文完整保留)")
    print()

    print("💡 关键点:")
    print()
    print("- Skill 不是 Agent，而是 Agent 可以加载的能力包")
    print("- Skill = Tools + 工具使用指南 + 元数据 + 示例")
    print("- mode='append' 追加工具说明，不破坏基础角色")
    print("- Agent 可以在对话中动态加载 Skill")
    print("- 加载 Skill 后，Agent 保持一致的角色和完整的记忆")
    print()

    print("📚 对话历史:")
    print("-" * 60)
    for i, msg in enumerate(memory.messages(), 1):
        role_emoji = {"system": "🔧", "user": "👤", "assistant": "🤖"}.get(msg.role, "❓")
        content = msg.content[:60] + "..." if len(msg.content) > 60 else msg.content
        print(f"{i}. {role_emoji} {msg.role}: {content}")
    print("-" * 60)
    print()

    print("=" * 60)
    print("   演示完成！")
    print("=" * 60)
    print()

    print("🎯 下一步:")
    print()
    print("1. 创建自己的 Skill:")
    print("   参考 skills/code_reviewer.py")
    print()
    print("2. 在实际项目中使用:")
    print("   agent = BaseAgent(...)")
    print("   agent.load_skill(your_skill)")
    print("   agent.run(user_input)")
    print()
    print("3. 查看文档:")
    print("   skills/README.md - 使用指南")
    print("   skills/CONTEXT_PRESERVATION.md - 上下文保护")
    print()


if __name__ == "__main__":
    main()
