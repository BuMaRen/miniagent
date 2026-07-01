# MiniAgent - 轻量级 Agent 框架

一个简洁、可扩展的 Python Agent 框架，提供 LLM 抽象、工具系统、记忆管理等核心能力。

## 项目结构

```
miniagent/
├── core/                      # 核心框架
│   ├── agent.py              # Agent 基类
│   ├── loop.py               # Agentic loop 控制流
│   └── config.py             # 配置管理
│
├── llm/                       # LLM 抽象层
│   ├── base/                 # 基础接口定义
│   │   └── client.py         # LLMClient 抽象类
│   ├── providers/            # Provider 实现
│   │   └── openai/           # OpenAI 兼容接口
│   └── data/                 # 数据结构
│       └── message.py        # Message 消息类
│
├── tools/                     # 工具系统
│   ├── schema.py             # ToolSchema 定义和自动生成
│   ├── registry.py           # ToolRegistry 工具注册
│   ├── executor.py           # ToolExecutor 工具执行
│   └── builtin/              # 内置工具
│       └── fs.py             # 文件系统工具
│
├── memory/                    # 记忆管理
│   ├── context.py            # ConversationContext
│   └── store.py              # 持久化存储
│
├── planning/                  # 任务规划
│   └── step.py               # Step/Plan 数据结构
│
├── skills/                    # 高级技能 (NEW!)
│   ├── code_analysis_tools.py  # 代码分析工具集
│   ├── code_reviewer.py        # Code Reviewer Agent
│   └── README.md              # Skills 使用文档
│
├── state/                     # 状态管理
│   └── runtime.py            # 运行时状态
│
├── hooks/                     # 生命周期钩子
│   └── lifecycle.py          # LifecycleHooks
│
├── main.py                    # 框架入口示例
├── debug_loop.py              # 调试脚本
├── example_code_reviewer.py   # Code Reviewer 示例
└── test_code_reviewer.py      # Code Reviewer 测试
```

## 核心概念

### Skill 是什么？

**Skill = 一组相关的工具函数**

```python
# Skill 的数据结构
code_reviewer_skill = [
    (read_file, schema_from_func(read_file)),
    (analyze_complexity, schema_from_func(analyze_complexity)),
    # ... 更多工具
]

# Agent 加载 Skill
agent = BaseAgent(...)
agent.load_skill(code_reviewer_skill)
```

### 概念层级

```
Agent (智能体)
  ├── LLM Client (大模型)
  ├── Memory (记忆)
  ├── Tool Registry (工具注册表)
  └── Skills (技能/工具集)
       ├── Skill A: [(tool1, schema1), ...]
       └── Skill B: [(tool2, schema2), ...]
```

## 核心特性

### 1. LLM 抽象层
- 统一的 `LLMClient` 接口
- 支持多 Provider（OpenAI、Anthropic、Ollama 等）
- 消息和工具调用的标准化

### 2. 工具系统
- 自动从 Python 函数生成 ToolSchema
- ToolRegistry 统一管理工具
- ToolExecutor 安全执行工具调用
- 内置文件系统工具

### 3. Agent Loop
- 标准的 Agentic Loop 控制流
- 自动处理工具调用链
- 支持最大循环深度限制
- 生命周期钩子扩展点

### 4. 记忆管理
- ConversationContext 管理对话历史
- 自动总结以适应上下文窗口
- 可持久化到文件系统

### 5. 技能系统 (Skill System)

**Skill = 工具集**，而非独立的 Agent：

```python
# 定义 Skill（工具列表）
my_skill = [
    (tool_func1, schema1),
    (tool_func2, schema2),
]

# Agent 加载 Skill
agent = BaseAgent(...)
agent.load_skill(my_skill)
```

**优势**：
- ✅ 轻量级：Skill 只是数据，不需要实例化
- ✅ 可组合：一个 Agent 可以加载多个 Skills
- ✅ 清晰语义：Skill 是能力，Agent 是执行者

**开箱即用的 Skills**：
- `code_reviewer_skill` - 代码审查工具集

## 快速开始

### 方式 1: 使用现成的 Skill（最简单）

```python
from llm.providers.openai.client import OpenAIClient
from skills.code_reviewer import create_code_reviewer_agent

# 创建 Agent
client = OpenAIClient(api_key="your-api-key", model="gpt-4o-mini")
agent = create_code_reviewer_agent(client)

# 使用
agent.run("请审查 core/loop.py 文件")
```

### 方式 2: 手动加载 Skill

```python
from core.agent import BaseAgent
from tools.registry import ToolRegistry
from tools.executor import ToolExecutor
from memory.context import ConversationContext
from skills.code_reviewer import code_reviewer_skill

# 创建 Agent
client = OpenAIClient(...)
registry = ToolRegistry()
executor = ToolExecutor(registry)
memory = ConversationContext(client, system_prompt="你是AI助手")

agent = BaseAgent(client, registry, executor, memory, None, None)

# 加载 Skill
agent.load_skill(code_reviewer_skill)  # mode="append" 默认，保留上下文

# 使用
agent.run("请审查代码")
```

### 方式 3: 查看完整演示

```bash
# 完整的端到端流程
python demo_complete_workflow.py

# 测试（无需 LLM）
python test_code_reviewer.py
```

## 基础使用

```python
from llm.providers.openai.client import OpenAIClient
from tools.registry import ToolRegistry
from tools.executor import ToolExecutor
from tools.builtin.fs import fs_tools
from memory.context import ConversationContext
from core.loop import agent_loop
from llm.data.message import Message

# 1. 创建 LLM 客户端
client = OpenAIClient(
    api_key="your-api-key",
    base_url="http://localhost:11434/v1",
    model="gemma4:e2b"
)

# 2. 注册工具
registry = ToolRegistry()
for func, schema in fs_tools:
    registry.register(schema.name, func, schema)
executor = ToolExecutor(registry)

# 3. 创建记忆上下文
context = ConversationContext(
    client,
    system_prompt="You are a helpful assistant."
)

# 4. 运行 Agent Loop
context.append(Message(role="user", content="帮我列出当前目录"))
agent_loop(client, registry.schemas(), executor, context)
```

### 使用 Code Reviewer Skill

**快速开始**：

```bash
# 完整流程演示
python demo_complete_workflow.py

# 工具测试（无需 LLM）
python test_code_reviewer.py
```

**代码使用**：

```python
# 方式 1: 使用辅助函数
from skills.code_reviewer import create_code_reviewer_agent
agent = create_code_reviewer_agent(client)
agent.run("请审查 core/loop.py")

# 方式 2: 手动加载 Skill
from skills.code_reviewer import code_reviewer_skill
agent.load_skill(code_reviewer_skill)
agent.run("请审查代码")
```

详见 **[skills/README.md](skills/README.md)** - 完整的 Skills 使用指南

## 设计原则

1. **简洁性**: 核心代码量少，易于理解和修改
2. **可扩展性**: 基于接口编程，易于添加新的 Provider、工具、技能
3. **解耦性**: LLM、工具、记忆、规划等模块相互独立
4. **实用性**: 提供实用的内置工具和示例 Skill

## 与其他框架对比

| 特性 | MiniAgent | LangChain | LlamaIndex |
|------|-----------|-----------|------------|
| 代码量 | ~1000 行 | 10w+ 行 | 5w+ 行 |
| 学习曲线 | 平缓 | 陡峭 | 中等 |
| 可定制性 | 高 | 中 | 中 |
| 内置功能 | 少而精 | 丰富 | 丰富 |
| 适用场景 | 学习/定制 | 生产环境 | RAG 应用 |

## 扩展建议

### 添加新的 Provider

1. 实现 `llm/base/client.py` 中的 `LLMClient` 接口
2. 在 `llm/providers/` 下创建对应目录
3. 参考 `llm/providers/openai/` 的实现

### 添加新的工具

```python
from tools.schema import schema_from_func

def my_tool(arg: str) -> str:
    """
    工具描述。
    
    Args:
        arg: 参数描述。
    """
    return f"Result: {arg}"

# 注册工具
registry.register("my_tool", my_tool, schema_from_func(my_tool))
```

### 创建新的 Skill

```python
from tools.schema import schema_from_func

# 定义工具函数
def tool1(arg: str) -> str:
    """工具1描述"""
    return f"Result: {arg}"

def tool2(arg: str) -> str:
    """工具2描述"""
    return f"Result: {arg}"

# 创建 Skill（工具列表）
my_skill = [
    (tool1, schema_from_func(tool1)),
    (tool2, schema_from_func(tool2)),
]

# 使用
agent = BaseAgent(...)
agent.load_skill(my_skill)
```

参考 [skills/code_reviewer.py](skills/code_reviewer.py) 的实现。

## 贡献

欢迎提交 Issue 和 Pull Request！

## 许可证

MIT License

## 致谢

本项目受到以下项目的启发：
- [LangChain](https://github.com/langchain-ai/langchain)
- [LlamaIndex](https://github.com/run-llama/llama_index)
- [AutoGPT](https://github.com/Significant-Gravitas/AutoGPT)
