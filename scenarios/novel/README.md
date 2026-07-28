# scenarios/novel —— 小说生成场景:第一版落地参考

本包是 [scenarios/README.md](../README.md) / [docs/workflow-design.md](../../docs/workflow-design.md)
描述的小说生成工作流的**第一个具体落地**,题材固定为:

> 现代历史系研究生意外穿越到西汉汉武帝建元年间的长安,起初只是想弄清楚自己
> 为何、如何来到这里并努力活下去,后来机缘之下随张骞出使西域,亲历"凿空"
> 西域的艰险历程。风格是**现实主义**——不写"金手指"式的穿越爽文,保留身体
> 的脆弱与制度的压迫感,人物会犯错、会害怕。

这一版已经写完并落地的是**第一章《初到西汉》**(见下方"已落地的产物"),
后续章节(包括随张骞出使西域的部分)按 workflow 设计留给下一轮迭代继续跑,
不在这一版里为了"看起来完整"而硬凑。

## 目录结构 —— 对应 [scenarios/README.md](../README.md) 的表格

| 文件 | 对应框架构件 | 说明 |
|---|---|---|
| `state_schema.py` | `state.StateSchema` | 故事圣经的具体字段定义,对应 [docs/story-bible-schema.md](../../docs/story-bible-schema.md);相比文档多了 `chapters[*].text/word_count` 两个字段(原因见文件内注释)。 |
| `toolsets/research.py` | `agent.ToolSet` | 历史考据小知识库(纪年、货币、路引制度、张骞出使背景…),供撰写/评审类 Stage 查证,减少"给古人塞现代常识"式的失真。 |
| `toolsets/qa.py` | `agent.ToolSet` | 中文字数统计与区间校验,供章节审校/最终校验使用。 |
| `stages.py` | `engine.Stage` + `agent.Agent` | 把上面的 ToolSet 挂到 Agent 上,组装成 [docs/workflow-design.md](../../docs/workflow-design.md) §4 表格里的每一个 Stage。**注意不是每个 Stage 都用 Agent**:`input_parsing`(填默认值)和 `final_qa`(字数/结构核对)是确定性计算,用普通函数当 executor——这正是 `Stage 不关心怎么产出输出` 的体现。 |
| `workflow.yaml` | Workflow 声明式定义 | 纯结构(sequence/loop/foreach/checkpoint),不含任何"大纲""章节"字样之外的场景语义;对应 workflow-design.md §4 的 YAML。 |
| `workflow.py` | `Workflow.from_spec` | 读 `workflow.yaml` + `stages.build_stage_registry()`,拼出可执行的 `Workflow`。 |
| `brief.yaml` | StoryBrief(§3.1 输入) | 本场景的默认输入,只有 `topic` 必填。 |
| `run.py` | 入口(真实运行) | 需要 `ANTHROPIC_API_KEY` 或 `OPENAI_API_KEY`。 |
| `offline_demo.py` | 入口(线下演示) | 不需要任何 API Key,用脚本化回复跑通整条流水线,验证接线是否正确;第一章正文就写在这个文件里的 `CHAPTER_1_TEXT`。 |
| `landing.py` | —— | 把 State Store 里的故事圣经"落地"成 `story_bible.json` / `chapters/*.md` / `manuscript.md`,由宿主代码(而非 LLM)负责磁盘 I/O。 |
| `output/` | —— | 已生成的产物(见下)。 |

## 已落地的产物

跑一遍 `offline_demo.py` 会在 `output/` 下生成:

- `output/story_bible.json` —— 完整故事圣经快照(meta/characters/world/foreshadowing/chapters)。
- `output/chapters/chapter_01.md` —— 第一章《初到西汉》正文。
- `output/manuscript.md` —— 标题(《凿空》)+ 简介 + 已完成章节的合并稿。

当前大纲只规划了第 1 章;`final_qa` 的报告里 `in_target_range: false`
是预期结果(目标 8000-20000 字,目前只有约 1700 字/1 章),不代表出错——
按 docs/workflow-design.md 的设计,中短篇应有 6-15 章,后续章节需要继续跑
`outline_generation`(重新规划完整大纲)与 `chapter_drafting` 循环补齐。

## 怎么跑

### 不需要 API Key:验证接线是否正确

```bash
pip install -r requirements.txt   # 需要 pyyaml(以及 openai/anthropic,仅导入检查用不到网络)
python -m scenarios.novel.offline_demo
```

内部原理:`offline_demo.py` 给每个需要 LLM 的 Stage 配一个
`ScriptedLLMClient`(手法与 `tests/agent/test_agent.py` 一致),按
`stages.py` 里约定的 JSON 契约预先写好这一次"生成"的内容;Critic 类
Stage 统一脚本成 `passed: true`,所以 Loop 一次通过、不触发 reviser——
这是为了让"流水线通不通"这件事确定性可复现,**不代表真实运行时 Loop
不会修订**,也不意味着第一章的内容是随手写的占位符:那就是这一版真正
要交付的正文。

### 真实生成(需要模型):

```bash
export ANTHROPIC_API_KEY=sk-...   # 或 OPENAI_API_KEY
python -m scenarios.novel.run --auto-approve
```

`run.py` 会把大纲评审(`confirm_outline`)、逐章确认(`chapter_pause`)这两个
人工断点交给一个交互式 CLI handler(除非传 `--auto-approve`):不通过时会追问
一句修改意见,该意见会驱动对应的 `outline_generation`/`chapter_revision`
重新生成,再拿新版本回来给你确认,不是单纯的"过/不过"两个哑按钮。Loop 超限
升级的断点默认接受最后一版并打印提示,供人工事后复核。状态持久化在
`--output-dir` 下的一个 JSON 文件里,进程中断后重跑同一条命令即可从断点续跑。

## 要把它"更专业地生产小说",预期改什么

按 [docs/framework-design.md](../../docs/framework-design.md) 的设计原则,
**不需要改动 workflow.yaml 里的流程结构**,主要工作量是:

1. 打磨 `stages.py` 里各 Stage 的系统提示词(尤其是 `_CHAPTER_DRAFTING_PROMPT`
   / `_CHAPTER_CRITIC_PROMPT` 的评判标准),这是决定文笔和一致性把控的关键。
2. 扩充 `toolsets/research.py` 的考据知识库(目前只覆盖了第一章用到的条目,
   张骞出使西域、河西走廊、匈奴等后续章节会用到的条目需要继续补充)。
3. 如果需要真正跑完整本(而不是只跑第 1 章),把 `offline_demo.py` 换成
   `run.py` 接真实模型,让 `outline_generation` 规划出完整的 6-15 章大纲,
   再让 `foreach` 逐章跑完。
