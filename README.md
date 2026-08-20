# MiniAgent

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

一个**与场景无关**的可复用 AI 工作流框架:提供 Stage(阶段)、ToolSet(能力挂载)、State Store(共享状态)、Loop(评审-修订循环)、ForEach(遍历子流程)、Checkpoint(人工断点)等通用构件。二次开发一个具体场景,通常只需要"定义 State Schema + 拼装这些原语 + 挂载/开发对应 ToolSet",而不需要重新设计流程结构。

当前已有一个示例场景用于验证这套抽象是否好用,具体内容见 [scenarios/development-guide.md](scenarios/development-guide.md)。二次开发/专业化某个场景时,预期的改动方式是打磨/扩充对应 Stage 上挂载的 ToolSet,而不是改动引擎结构。

## 项目定位

- **框架层**:Stage、ToolSet、State Store、Loop、ForEach、Checkpoint、Breaker、Continuer 等通用构件,不绑定任何具体场景,理论上可复用于代码审查、报告撰写等其他多阶段生成任务。这是二次开发时应该复用、不应该改动结构的部分。
- **场景层**:`scenarios/example/`(测试用例设计工作流)是当前用来验证这套抽象是否好用的具体实例——用框架原语拼出流程,并挂载场景专属的 ToolSet 与 State Schema。

## 项目结构

框架层(`engine`/`agent`/`state`/`llm`/`tools`)不含任何场景语义,场景层内容全部落在 `scenarios/` 下。

```
miniagent/
├── engine/                     # 工作流引擎(框架核心,场景无关)
│   ├── stage.py                #   Stage:输入→输出契约 + Node 统一协议
│   ├── context.py              #   RunContext:运行期共享上下文 + 生命周期 hook
│   ├── workflow.py             #   Workflow:顶层节点编排 + 失败续跑(WorkflowFailure)
│   └── primitives/             #   控制流原语
│       ├── sequence.py         #     顺序执行
│       ├── loop.py             #     迭代:同一份输入反复跑 body,配合 Breaker/Continuer 判定退出/重开(含超限策略)
│       ├── foreach.py          #     遍历子流程
│       ├── checkpoint.py       #     人工断点(同步问答)
│       ├── breaker.py          #     提前终止 Loop/ForEach(相当于 break)
│       └── continuer.py        #     跳过本轮、从 body 头重开下一轮(仅对 Loop 生效,相当于 continue)
│
├── agent/                      # 能力挂载层
│   ├── agent.py                #   Agent = LLM + 工具 + 工具集 + 记忆(agentic loop)
│   ├── toolset.py              #   ToolSet:一组 (func, schema)
│   └── memory.py               #   对话记忆(短期,区别于 State Store)
│
├── state/                      # 共享状态
│   ├── store.py                #   StateStore 抽象:get/patch/append/slice/snapshot
│   ├── schema.py               #   StateSchema:场景方定义字段与校验
│   └── backends/               #   内存后端 + JSON 文件后端(断点恢复)
│
├── llm/                        # LLM 抽象层
│   ├── client.py               #   LLMClient 接口 + ChatResponse
│   ├── message.py              #   Message / ToolCall 标准结构
│   └── providers/               #   OpenAI / Anthropic / 智谱(zai-sdk)实现
│
├── tools/                      # 工具系统
│   ├── schema.py               #   ToolSchema + schema_from_func(自动生成)
│   ├── registry.py             #   ToolRegistry
│   └── executor.py             #   ToolExecutor(安全执行 + 异常回填)
│
└── scenarios/                  # 场景层:二次开发挂载点(见 scenarios/development-guide.md)
```

场景方直接用 Python 组合 `Stage` 与 `engine/primitives/` 下的控制流原语拼出
`Workflow`(见 `scenarios/example/workflow.py`),
不存在从 YAML 等声明式定义编译节点这一层——详见 [scenarios/development-guide.md](scenarios/development-guide.md)。

## 关键设计点

1. **Node 统一协议** — Stage 和各控制流原语都实现 `run(ctx, inputs)`,因此能任意嵌套(`ForEach` 的 body 可以是 `Loop`)。这是"用少量原语组合出任意流程"的基础。
2. **reads/writes 声明式** — Stage 显式声明需要读写的状态切片,既能只向 LLM 注入相关上下文(控制成本),又能做依赖分析(判断哪些 Stage 可并行)。
3. **Loop 的退出与超限策略** — 是否重开下一轮/提前结束由放进 body 里的普通 Node 决定:`Continuer` 相当于 `continue`(跳过本轮剩余节点,从 body 头重开),`Breaker` 相当于 `break`(终止最近的外层 Loop/ForEach)。判定逻辑放在场景自己的 Node 里,引擎不认识任何业务字段名;超限则有 `accept_last / escalate_to_checkpoint / raise` 三种策略,杜绝死循环。
4. **两种记忆分离** — `agent/memory.py` 是单次 Agent 运行内的短期对话记忆;`state/` 是跨 Stage 的长期结构化事实。用摘要保证连贯,用结构化状态保证事实一致,职责分开。
5. **能力通过 ToolSet 挂载,而非改结构** — 换场景/做专业化的预期改动是"换一套 ToolSet + 换一份 State Schema",Stage/Loop/ForEach 的骨架不动。

## 运行测试

框架层的单元测试在 `tests/`(镜像 `engine`/`agent`/`state`/`llm`/`tools` 的目录结构),只用标准库 `unittest`,无需额外依赖即可跑：

```
PYTHONPATH=src python3 -m unittest discover -s tests -t .
```

`tests/llm/test_openai_provider.py`、`tests/llm/test_anthropic_provider.py`、`tests/llm/test_zhipu_provider.py` 覆盖三个 Provider 的消息格式转换;若未安装对应的 `openai`/`anthropic`/`zai-sdk`(`requirements.txt` 里的三个依赖),对应的文件会自动跳过而非报错。

## 安装

发布到 PyPI 后,在其他项目中安装:

```
pip install bumaren-agent-workflow
```

Python 中使用组织前缀命名空间导入:

```python
from bumaren_agent_workflow import Agent, Workflow
from bumaren_agent_workflow.engine.primitives import Sequence
```

版本由 Git 标签自动生成;发布时推送形如 `v0.1.3` 的新标签即可:

```
git tag v0.1.3
git push origin v0.1.3
```

首次发布前,在 PyPI 的 `Publishing` 页面添加一个 pending Trusted Publisher:
owner 为 `BuMaRen`, repository 为 `miniagent`, workflow 为 `publish-pypi.yml`, environment
为 `pypi`。后续发布无需保存 PyPI token 到 GitHub Secrets。

## 二次开发一个新场景

参见 [scenarios/development-guide.md](scenarios/development-guide.md)。典型步骤:

1. 定义 `state_schema.py`(该场景要跨步骤追踪哪些事实,用 `state.schema.StateSchema` 直接构造)。
2. 开发 `toolsets/`(每个 Stage 需要的工具集,**主要工作量所在**)。
3. 写 `prompts.py`(每个 Agent 的提示词;共享片段提成模块级常量复用)。
4. 在 `nodes/` 下按业务分组,每个模块提供 `build_xxx_stage()` 函数:声明节点的 executor / reads / writes / output_schema / tools / prompt。
5. 在 `workflow.py` 的 `build_workflow()` 里用 `Sequence`/`Loop`/`ForEach`/`Checkpoint` 直接拼出流程。
6. 在 `run.py` 里组装 LLMClient / StateStore / RunContext 并运行。

参见 `scenarios/example/` 这一个完整范例。

## 文档

- [scenarios/development-guide.md](scenarios/development-guide.md) — **场景开发指南**:动手向导,一步步把框架构件拼成一个新场景

## 状态

v0.1.1:框架层(`tools/` → `llm/` → `state/` → `agent/` → `engine/`)与首个场景 `scenarios/example/`(测试用例设计工作流)均已实现,`tests/` 下有对应单元测试覆盖。
