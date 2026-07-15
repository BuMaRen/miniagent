# scenarios/ —— 场景层(二次开发挂载点)

这里存放**基于框架层构建的具体场景**。框架层(engine / agent / state / llm / tools)
不放任何场景语义;所有"小说""报告"之类的内容都落在这个目录下的子包里。

## 一个场景通常包含什么

参照 [docs/framework-design.md](../docs/framework-design.md) §8 的二次开发步骤,一个场景子包(如 `scenarios/novel/`)一般包含:

| 文件/模块 | 职责 | 对应框架构件 |
|---|---|---|
| `state_schema.py` | 定义该场景的共享状态结构 | `state.StateSchema`(小说见 [docs/story-bible-schema.md](../docs/story-bible-schema.md)) |
| `skills/` | 每个 Stage 需要的工具集(**主要开发工作量**) | `agent.Skill` |
| `stages.py` | 把 Skill 挂到 Agent 上,组装成一个个 `Stage` | `engine.Stage` |
| `workflow.py` | 用 Sequence/Loop/ForEach/Checkpoint 拼出流程 | `engine.Workflow` + `engine.primitives` |
| `run.py` | 组装 LLMClient / StateStore / RunContext 并运行 | 入口 |

## 从框架到场景的映射(以小说为例)

- 流程结构见 [docs/workflow-design.md](../docs/workflow-design.md) §4 的 Workflow 定义。
- 大纲评审、章节审校 = 同一个 `Loop` 原语的两次实例化。
- 逐章撰写 = `ForEach(chapters, body=Loop(draft, critic, revise))`。
- 故事圣经 = `StateSchema` 的一个实例。

## 关键点

**专业化一个场景 = 打磨 `skills/` + 调整 `state_schema.py`,而不是改动框架层。**
新增场景时,复制这套目录约定,替换成你自己的 State Schema 与 Skill 即可。
