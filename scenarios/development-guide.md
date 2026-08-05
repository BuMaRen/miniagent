# 场景开发指南

本文档面向想在 MiniAgent 框架上**开发一个新场景**的人,是一份动手向导(怎么落地),
不是概念设计文档(那是 [docs/framework-design.md](../docs/framework-design.md))。建议
顺序:先读一遍 framework-design.md 建立概念模型(Node/Stage/Agent/ToolSet/StateStore/
四个控制流原语),再回来看本文档"怎么把这些概念拼成一个跑得起来的场景包"。

阅读本文档前请先确认一件事:**框架层(`engine`/`agent`/`state`/`llm`/`tools`)不需要,
也不应该改动。** 开发一个新场景 = 在 `scenarios/` 下新建一个包,用框架已经提供的构件
拼出你自己的流程、状态、能力,仅此而已。

场景包**直接用 Python 组装**:场景包里一个 `workflow.py` 直接 `Stage`/`Sequence`/
`Loop`/`ForEach`/`Checkpoint` 拼出 `Workflow`,没有 YAML 声明式配置这一层——想知道
某个节点具体读写什么状态、挂了什么 ToolSet,直接看 Python 源码即可,不需要在"配置"
和"配置的解释器"之间来回跳。

## 0. 可以直接抄的范例

仓库里已经有两个真实场景,遇到具体问题时直接去看它们的源码往往比读文档更快:

| 场景 | 特点 | 适合参考什么 |
|---|---|---|
| [`scenarios/novel/`](novel/) | 题材写死在流程 prompt 里;有人工审阅断点 | Loop/ForEach/Checkpoint 三者组合、评审节点的状态旁路写回 |
| [`scenarios/short/`](short/) | 内容与流程严格分离;全自动无人工介入 | 确定性体检与 LLM 判断的分工、大量小节点的 `nodes/` 目录组织方式 |

如果还没准备好挂 LLM,只想先把"数据怎么声明"和"四个控制流原语怎么用"跑一遍
看明白,看 [`scenarios/examples/`](examples/)——不需要 API Key,`python -m
scenarios.examples.run` 秒开秒跑,尤其把 `Loop` 的 `continue_when`("continue")
与 `Breaker`("break")这两个容易混淆的概念拆开单独演示,§6 的写法就是照抄那里。

两者跑在同一套引擎上(`Sequence`/`Loop`/`ForEach`/`Checkpoint`/`Stage`),差别只在
业务需求(题材是否写死、要不要人工介入),不在组装方式。

## 1. 一个场景包长什么样

一个场景包(`scenarios/<name>/`)通常包含这些东西:

```
scenarios/<name>/
├── state_schema.py        # 该场景要跨节点追踪的共享状态结构(state.schema.StateSchema)
├── nodes/                 # 按业务分组,每个模块提供 build_xxx_stage() 函数
│   ├── common.py           #   跨节点复用:Agent 组装、状态路径常量、判定合并
│   ├── outline.py           #   build_outline_generation_stage() / build_outline_critic_stage()
│   └── ...
├── toolsets/*.py           # 每个 Stage 需要的能力(**主要开发工作量**)
├── prompts.py              # 流程侧提示词,模块级字符串常量
├── workflow.py              # build_workflow(client_factory) -> Workflow,在这里拼 Sequence/Loop/ForEach
├── landing.py               # 把最终 State 落地成 Markdown/JSON 等交付物(可选)
├── brief.yaml / brief.py   # 用户输入的题材/设定,与"流程怎么跑"严格分开(可选,见 §7)
└── run.py                  # 组装 LLMClient / StateStore / RunContext 并运行
```

**唯一不该出现的东西:对 `engine`/`agent`/`state`/`llm`/`tools` 里任何文件的修改。** 如果
你发现自己想改这些目录,先重新检查一遍是不是把"业务策略"当成了"控制流形状"去改引擎
——判断标准见 framework-design.md §6.5。

## 2. 先想清楚:拆几个 Stage、哪里要 Loop、哪里要 ForEach

在写任何代码之前,按 framework-design.md §8 的步骤在纸面上想清楚这几件事,后面的编码
只是把这些结论翻译成 Python:

1. **State Schema**:这个场景要跨步骤追踪哪些事实?(小说场景是"故事圣经":人物、
   世界观、章节大纲;short 场景是"制作单":骨架、角色、爽点、分节大纲)
2. **拆 Stage**:整个任务拆成哪几步,每步的输入输出是什么?
3. **哪些环节需要质检**:给对应 Stage 套一层 `Loop`(生成 → 评审,`continue_when`
   是一个判定谓词,读评审产出的"还要再改一轮"字段)。
4. **哪些环节要对列表重复处理**(逐章/逐节/逐条):套一层 `ForEach`。
5. **哪些节点需要人工介入**:插入 `Checkpoint`;如果人工审阅该落在某个 `Loop` 的评审
   环节里,直接加在该 `Loop` 的 `body` 末尾(排在 AI critic 之后)。
6. **每个 Stage 需要什么能力**:开发对应的 `ToolSet`——这是主要工作量所在,1-5 步
   通常一次设计好之后很少再变。

想清楚这 6 点之后,才进入"怎么落地成代码"这一步。

## 3. 怎么组装:节点定义 + Workflow 拼装

### 3.1 每个节点怎么定义

`nodes/<group>.py` 里每个 `build_xxx_stage(client)` 函数负责"这一个节点是什么":

```python
def build_outline_generation_stage(client: LLMClient) -> Stage:
    agent = make_agent(client, prompts.OUTLINE, output_schema=OUTLINE_AGENT_SCHEMA)

    def executor(ctx: RunContext, inputs: dict) -> dict:
        state = inputs.get("state", {})
        out = agent.run(ctx, {...})           # 组装 payload,交给 Agent 跑一次
        return {SECTIONS_PATH: [...], PAYOFFS_PATH: [...]}   # 拼装/裁剪模型的产出

    return Stage(
        name="outline_generation",
        executor=executor,
        reads=[...],
        writes=[SECTIONS_PATH, PAYOFFS_PATH],
        output_schema=OUTLINE_OUTPUT_SCHEMA,
    )
```

如果节点不需要对模型的产出做任何加工(直接把 Agent 的输出当 Stage 的输出),
`executor` 可以就是 `agent.run` 本身,不必包一层:

```python
def build_concept_expansion_stage(client: LLMClient) -> Stage:
    agent = make_agent(client, prompts.CONCEPT_EXPANSION, output_schema=CONCEPT_EXPANSION_OUTPUT_SCHEMA)
    return Stage(
        name="concept_expansion",
        executor=agent.run,
        reads=[META_PATH],
        writes=[META_PATH],
        output_schema=CONCEPT_EXPANSION_OUTPUT_SCHEMA,
    )
```

`make_agent` 是场景方在自己的 `nodes/common.py` 里写的一个小工具函数,不是框架接口:

```python
def make_agent(client, system_prompt, toolsets=(), output_schema=None) -> Agent:
    agent = Agent(
        client=client,
        memory=ConversationMemory(system_prompt=system_prompt),
        registry=ToolRegistry(),       # 每个 Agent 独占一张,不要共用全局表
        max_steps=8,
        output_schema=output_schema,   # 非 None 时开启 Provider 的结构化输出模式
    )
    for toolset in toolsets:
        agent.load_toolset(toolset)
    return agent
```

纯函数节点(不需要 LLM 的计算,比如默认值填充、字数统计、结构校验)直接写函数,
`executor` 参数接受任何 `(ctx, inputs) -> outputs` 的可调用对象,不必是 Agent:

```python
def input_parsing_executor(ctx: RunContext, inputs: dict) -> dict:
    ...

def build_input_parsing_stage() -> Stage:
    return Stage(name="input_parsing", executor=input_parsing_executor, writes=[META_PATH])
```

节点自身表达不了的副作用(比如某个评审节点在过审后还要旁路写回一段状态,这段
额外的状态字段放不进评审节点自己的输出契约),直接写一个满足 Node 协议(`name` +
`run(ctx, inputs)`)的包装类,把原节点包在里面——不需要继承任何基类:

```python
class _ChapterCriticWithStatusWriteback:
    def __init__(self, node: Node) -> None:
        self._node = node
        self.name = node.name

    def run(self, ctx: RunContext, inputs: dict) -> dict:
        verdict = self._node.run(ctx, inputs)
        if not verdict.get(NEEDS_REVISION_KEY):
            _set_chapter_status(ctx, ..., "reviewed")
        return verdict
```

见 [scenarios/novel/nodes/chapter.py](novel/nodes/chapter.py) 的完整实现与取舍说明
(framework-design.md §6.5 "场景自定义节点"是这一手法的设计依据)。

### 3.2 Workflow 怎么拼

`workflow.py` 的 `build_workflow(client_factory)` 负责"这些节点怎么串":直接
`import` 各 `nodes/*.py` 的 `build_xxx_stage`,用 `Sequence(name=..., nodes=[...])`/
`Loop(name=..., body=[...], continue_when=..., max_iterations=..., on_exceed=...)`/
`ForEach(name=..., items_path=..., body=...)` 拼出一棵 `Node` 树,最后包成
`Workflow(name=..., nodes=[...], state_schema=...)`:

```python
def build_workflow(client_factory: ClientFactory) -> Workflow:
    def client_for(stage_name: str, model: str | None = None) -> LLMClient:
        return client_factory(stage_name, model)

    nodes = [
        Sequence(name="setup", nodes=[
            build_input_parsing_stage(),
            build_concept_expansion_stage(client_for("concept_expansion")),
        ]),
        Loop(
            name="outline_loop",
            continue_when=lambda ctx, outputs: outputs.get("needs_revision", False),
            max_iterations=2,
            body=[
                build_outline_generation_stage(client_for("outline_generation")),
                build_outline_critic_stage(client_for("outline_critic")),
            ],
            on_exceed=OnExceed.ACCEPT_LAST,
        ),
        ForEach(
            name="section_loop",
            items_path="short_story.sections",
            body=Sequence(nodes=[build_section_drafting_stage(client_for("section_drafting")), ...]),
        ),
        build_final_qa_stage(),
    ]
    return Workflow(name="short_story_generation", nodes=nodes, state_schema=SHORT_STORY_SCHEMA)
```

`client_factory` 的签名是 `(stage_name: str, model: str | None) -> LLMClient`,由
`run.py` 提供(通常按 `model` 分组、惰性构造并复用 client)。哪个节点用哪个模型,
在这里**直接传字面量**决定即可——"一组节点共用同一个模型"就是把同一个字符串传给
这组节点各自的 `client_for` 调用,不需要额外的继承/解析机制:

```python
build_concept_expansion_stage(client_for("concept_expansion", "claude-sonnet-5")),
build_character_world_design_stage(client_for("character_world_design", "claude-sonnet-5")),
# 其余节点不传 model(即传 None),退回 client_factory 自己的默认模型。
```

## 4. 状态设计(State Schema)

用 `state.schema.StateSchema` 描述这个场景的共享状态长什么样,直接用 Python 类型树
构造(标量类型、`OneOf` 枚举、`[子描述符]` 同构列表、`ANY` 不约束):

```python
# state_schema.py
from state.schema import OneOf, StateSchema

CHARACTER = {
    "id": str,
    "name": str,
    "role": OneOf("protagonist", "antagonist", "supporting"),
}
SHORT_STORY_DEFINITION = {"short_story": {"characters": [CHARACTER], ...}}
SHORT_STORY_SCHEMA = StateSchema(name="short_story", definition=SHORT_STORY_DEFINITION)

def empty_state() -> dict:
    return SHORT_STORY_SCHEMA.empty()
```

完整的类型树写法见 [state/schema.py](../state/schema.py) 模块开头的文档。几条要
记住的取舍:

- 对象字段默认拒绝未声明的键(帮你抓拼写错误),但**不强制必填**——写入是增量式的
  (`patch` 只带本次变更的字段),校验的是"类型对不对",不是"填没填全"。
- 没有专门的"可空"类型:一个字段要么有确定类型(缺省时是该类型的零值),要么整个子树
  用 `ANY` 完全不约束。
- 子结构(如 `CHARACTER`)常常要在多处复用(既是共享状态的一部分,也是某个 Stage
  `output_schema` 的一部分)——提成模块级常量,在 `nodes/*.py` 里直接 `import` 复用,
  不要重复内联同一段结构(参考 [scenarios/short/nodes/outline.py](short/nodes/outline.py)
  怎么从 `state_schema.py` 借用 `SECTION`/`PAYOFF`)。
- `StateSchema.empty()` 生成一份类型正确的空状态,作为一次新运行的起点。
- `StateSchema.to_prompt_example()` 把 definition 渲染成占位符 JSON,如果你的场景需要
  在提示词里给一份格式示例可以用它生成,但通常不需要——`output_schema` 已经通过
  Provider 的结构化输出模式保证了字段与类型,不必在提示词里再手写一份 JSON 示例。
- 引擎自己写的 `_loop.<name>.last`、`_foreach.<name>.index`/`.item` 这两个记账命名
  空间**不需要**、也**不应该**写进你的 `definition`——它们是引擎运行期自动创建的,
  声明了反而会被 `StateSchema.validate` 的"未声明字段拒绝"规则挡住。

## 5. 每个 Stage:输入输出契约 + reads/writes

`Stage`(`engine/stage.py`)是最小执行单元,构造函数:

```python
Stage(
    name: str,
    executor: Callable[[RunContext, dict], dict],   # 或一个 Agent 实例(它的 .run 就是这个签名)
    input_schema: StateSchema | None = None,
    output_schema: StateSchema | None = None,
    reads: Sequence[str] = (),     # 执行前从 State Store 注入哪些切片(合并进 inputs["state"])
    writes: Sequence[str] = (),    # 执行后把 outputs 里对应字段写回 State Store 的哪些路径
)
```

几条约定务必记住:

1. **`reads` 只拿你真正需要的切片。** 引擎不会把全量状态塞给你的 executor——这既是
   控制上下文成本的手段,也是可读性:一眼看 `reads` 就知道这个节点依赖什么。
2. **`writes` 是可选的。** 数据有两条通道:①上一个节点的 `outputs` 直接作为下一个
   节点的 `inputs`(不落 State,只在相邻节点间有效);②只有 `writes` 声明的切片才写回
   State Store。只有当某个事实需要被**非相邻的后段**读取,或需要支持断点恢复时,才
   写 State。
3. **Loop 内部跨轮次要传的东西走游标,不走 `writes`。** 见 §6。
4. **executor 收到的 `inputs` 里,`inputs["state"]` 是按 `reads` 切出来的那一份**
   (`{path: value}` 形式,不是整棵状态树)——`Stage.run` 会自动做这一步注入
   (`ctx.state.slice(self.reads)`)。

`Agent.run` 的最终产出约定是一个 JSON 对象(不是合法 JSON 时会退化成
`{"output": content}`,不会让整个 run 失败,但基本等于这个节点白跑了一次,排查时先
看这里)。

## 6. 四个控制流原语实战

### Sequence —— 顺序

```python
from engine.primitives.sequence import Sequence
Sequence(name="setup", nodes=[stage_a, stage_b])
```
上一个节点的 `outputs` 直接作为下一个的 `inputs`。没有特殊行为。

### Loop —— 反复跑同一份输入直到判定放行

```python
from engine.primitives.loop import Loop, OnExceed, loop_cursor_path

Loop(
    name="outline_loop",
    body=[outline_generation, outline_critic],   # 一轮依次跑,规则同 Sequence
    continue_when=lambda ctx, outputs: outputs.get("needs_revision", False),  # 真 = 还要重开一轮
    max_iterations=2,
    on_exceed=OnExceed.ACCEPT_LAST,   # 还有 ESCALATE_TO_CHECKPOINT / RAISE
)
```

`continue_when` 是一个判定谓词 `(ctx, outputs) -> bool`,不是状态路径字符串——和
`Breaker` 的 `predicate` 同一种签名风格(见下面的 Breaker 小节)。几条不看源码容易
踩的坑:

- **谓词会在 body 里每一个节点跑完后都被调用一次**(不是只调用"评审"那一个,也
  不是整条 body 跑完才判一次),所以要用 `outputs.get("needs_revision", False)`
  这类防御性写法,不要用 `outputs["needs_revision"]`——生成类节点的 outputs 里
  没有这个字段,直接按键取会在生成节点跑完后就抛 `KeyError`。
- 判定字段的极性建议朝"还要再改"为真去命名(如 `needs_revision`)而不是
  `passed`——引擎侧的极性是固定的(谓词返回 `True` 才重开一轮),但谓词内部想
  怎么取反完全是你自己的事(比如上游用 `passed` 命名,谓词写成
  `lambda ctx, outputs: not outputs.get("passed", True)` 也完全可以)。
- **`body` 顺序很重要**:`[生成, AI 评审, 人工确认]` 才能让 AI 判否时短路掉人工
  确认这一步(判定放在每个节点之后,AI 判否时 Loop 立即重开一轮,不会往下跑到
  人工确认);反过来排会导致人工确认判否之后 body 还傻乎乎往下跑。同一个
  `continue_when` 谓词会在 AI 评审、人工确认两个节点跑完后各被调用一次,只要两者
  outputs 形状一致(都是 `{needs_revision, feedback}`),写一个谓词就够了,不需要
  分别包装。
- **下一轮怎么知道上一轮为什么没过**:body 里的第一个节点(通常是"生成"节点)要在
  自己的 `reads` 里加上 `loop_cursor_path("outline_loop")`(即
  `"_loop.outline_loop.last"`),这样能读到上一个节点(通常是评审)的产出。**务必用
  `loop_cursor_path(name)` 函数拼这个路径,不要手写字符串**——否则改名字时容易漏改
  一处导致读写对不上,`Loop`/`workflow.py` 两处应该共用同一个 `xxx_LOOP_NAME` 常量。
  这条游标和 `continue_when` 判定谓词是两件独立的事:游标只负责"跨轮次传数据"
  (评审意见),判定谓词直接对着刚跑完的节点的 outputs 求值,不需要经过游标、也
  不需要经过 State 走一趟。
- **没有人工介入时,`on_exceed` 不要用 `ESCALATE_TO_CHECKPOINT`**——没有人在等着裁决,
  升级只会把流程卡死(`ctx.checkpoint_handler` 为 `None` 时直接报错)。全自动场景
  (如 `short/`)两个 Loop 都用 `ACCEPT_LAST`。
- 跑满 `max_iterations` 仍不过关、又用了 `ACCEPT_LAST` 时,把"这一处仍不达标"的
  事实交代清楚(如 `short/` 的 `final_qa` 会把残留问题写进 `qa_report`),不要悄悄
  放过去。

### ForEach —— 遍历一个列表

```python
from engine.primitives.foreach import ForEach

ForEach(
    name="section_loop",
    items_path="short_story.sections",     # 遍历这个列表
    body=Sequence(nodes=[drafting, Loop(...)]),   # 对每个元素跑的子流程
)
```

- `ForEach` **只负责重复**,不负责连贯性——"第 N 项能看到前 N-1 项的产物"是 body
  里的 Stage 通过 `reads`/`writes` 读写共享 State 的自然结果,不是靠 `ForEach` 塞什么
  魔法字段。
- body 里的 Stage 通过 `reads=[foreach_item_path("section_loop")]`(即
  `"_foreach.section_loop.item"`)读到"当前遍历到的元素",和读任何一个普通状态切片
  完全一样——同样建议用 `foreach_item_path(name)` 函数拼路径,不要手写字符串。
- 下标游标天然支持断点续跑:失败后重跑同一条命令,`ForEach` 会从上次停下的下标接着走。

### Checkpoint —— 人工断点

```python
from engine.primitives.checkpoint import Checkpoint

Checkpoint(
    name="confirm_outline",
    prompt="大纲已通过 AI 评审,请确认……",
    resume_input_schema=critic_output_schema,   # 人工输入要满足的契约
)
```

- 需要 `ctx.checkpoint_handler`(见 §8),没配置就是配置错误、直接报错——不是"挂起等
  以后再答"的意思;真要"以后再答",在 handler 内部抛异常即可(会被通用失败路径接住,
  见 §8 的续跑机制)。
- 放进某个 `Loop` 的 `body` 末尾(AI critic 之后),就"零成本"组合出了"AI 先挡、
  通过后人工再把关"——`Checkpoint.run()` 的返回值(流入的 inputs 与人工输入合并)
  天然是评审契约的超集,可以直接当 `Loop.body` 里的一关,人工判否同样驱动下一轮重写。

### Breaker —— 提前跳出 Loop/ForEach(不常用,按需了解)

```python
from engine.primitives.breaker import Breaker
Breaker(name="early_exit", predicate=lambda ctx, inputs: 某个条件)
```
放进 `Loop`/`ForEach` 的 body 里,`predicate` 为真时抛 `LoopBreak`,由最近的外层
`Loop`/`ForEach` 捕获:对 `Loop`相当于"提前放行、接受当前结果结束循环"(区别于跑满
`max_iterations` 触发的 `on_exceed`);对 `ForEach` 相当于 Python 的 `break`。

## 7. Prompt 与用户输入分离(强烈建议遵守)

这是 `scenarios/short/` 验证过的一条经验,`scenarios/novel/` 是反例(把题材焊死在了
流程 prompt 里,导致那份场景只能服务一个题材)。约定:

- **用户 prompt**(写什么:题材、主角、禁忌……)落在一份独立的 brief 文件里
  (`brief.yaml` + 校验代码 `brief.py`),只经 State 的 `xxx.brief` 字段与流程相接。
- **流程 prompt**(怎么写:结构、语言底线、各节点职责)落在 `prompts.py` 里,**不
  允许出现任何具体的人名/时代/世界观/题材内容**;换任何题材都不需要改这里一个字。
- 如果流程 prompt 需要一份"没有更具体设定时的默认参考"(如 `short/` 的
  `TROPE_BANK` 起步词库),这是该边界唯一允许的例外,且要在代码注释里写清楚为什么
  ("只在用户留空时给一个参考起点,用户写明的部分它让位")。

判断你新写的一段 prompt 是否越界的简单测试:**换一个完全不同的题材,这段文字要不要
改一个字?** 要改,就说明它混入了用户输入该管的内容。

## 8. 运行入口 `run.py` 该做哪些事

`run.py` 通常要做这几件事(可直接参考 [`scenarios/short/run.py`](short/run.py) 或
[`scenarios/novel/run.py`](novel/run.py)):

1. **加载用户 brief**,先校验、后组装——设定写错时应该立刻报错,而不是跑到第一个
   节点才失败(那时可能已经产生了 API 调用费用)。
2. **构造 `client_factory: (stage_name, model) -> LLMClient`**,按需惰性构造并按
   `model` 分组复用 client(同一个 model 不要反复建连接)。`model` 为 `None` 时退回
   一个默认模型/环境变量。
3. **构造 `StateStore`**(通常是 `state.backends.json_file.JsonFileStateStore`,自带
   落盘,支持断点恢复)。新运行时 `store.load(schema.empty())`;若要强制重新开始
   (常见做法是加一个 `--fresh` 参数),显式清空。
4. **构造 `RunContext`**:传入 `state`、可选的 `checkpoint_handler`(有人工介入才需要)、
   `hooks`(打日志用)、以及从 sidecar 文件读到的 `resume`(见下)。
5. **续跑机制**:`workflow.run()` 在顶层节点失败时抛 `WorkflowFailure`(带
   `node_index`/`inputs`/`node_name`)。`run.py` 捕获后把这三样存进一份 sidecar
   JSON(状态本身已经由 `JsonFileStateStore` 逐次落盘,sidecar 只补"顶层游标"这一块
   State Store 盖不住的信息);下次启动时读回构造 `ResumePoint`,`Workflow.run` 会
   跳过已成功的前序顶层节点,只从失败的节点重新开始。
6. **落地产物**:调用场景自己的 `landing.py` 把最终 `state_store.snapshot()`
   转成 Markdown/JSON 等交付物。

## 9. 测试

框架层与场景层的测试都在 [`tests/`](../tests/)(镜像 `scenarios/` 的目录结构,如
`tests/scenarios/short/`),只用标准库 `unittest`:

```bash
python3 -m unittest discover -s tests -t .
```

给新场景写测试时,建议至少覆盖:

- **确定性 executor/toolset 的纯函数逻辑**(字数统计、结构校验、判定合并这类不需要
  真的调用 LLM 的部分)——这部分最容易测,也最该测,因为它们是"能算的不交给模型判断"
  这条原则的落地。
- **State Schema 的校验行为**(必填/类型/枚举是否符合预期)。
- **流程结构的装配是否正确**——不一定要真的调 LLM,可以用一个返回固定内容的假
  `LLMClient` 走一遍 `build_workflow` + `Workflow.run`,验证 `reads`/`writes`/游标
  路径接得对不对(`tests/scenarios/short/test_pipeline.py`、
  `tests/scenarios/novel/test_review_rounds.py` 是这类验证的例子)。
- **prompt 与用户输入分离的边界**(如 `short/` 的测试专门守着"流程 prompt 里不出现
  任何题材内容"这条约束)——如果你的场景也有类似的分层约定,值得写一条同类测试。

## 10. 开发新场景 Checklist

1. 按 §2 想清楚:State Schema、Stage 拆分、哪里要 Loop/ForEach、哪里要 Checkpoint。
2. 写 State Schema(§4)。
3. 为每个 Stage 开发/挂载 ToolSet(§1 表格里标注的"主要开发工作量所在";
   `agent.toolset.ToolSet.from_funcs(name, [func1, func2, ...])` 是最快的构造方式,
   会从函数签名 + docstring 自动生成工具的 JSON Schema)。
4. 写流程 prompt,严守 §7 的分离约定。
5. 按 §3、§5、§6 把 Stage 和控制流原语拼成 Workflow。
6. 写 `run.py`(§8)。
7. 写 `landing.py` 把产物落地成人可读的交付物。
8. 补测试(§9)。
9. 在 `scenarios/README.md` 里补一行,登记这个新场景。

## 11. 参考文档

- [docs/framework-design.md](../docs/framework-design.md) —— 框架设计的权威来源,概念
  定义与取舍理由都在这里,本文档里的实战建议如果与它冲突,以它为准。
- [docs/workflow-design.md](../docs/workflow-design.md)、
  [docs/story-bible-schema.md](../docs/story-bible-schema.md) —— `novel` 场景作为
  框架第一个实例的完整设计。
- [scenarios/README.md](README.md) —— 场景层总览。
- [scenarios/novel/](novel/)、[scenarios/short/](short/) —— 两个完整可运行范例,
  连同各自的 `README.md`。
- [scenarios/examples/](examples/) —— 不挂 LLM 的原语速查手册,数据声明 + 四个
  控制流原语(尤其 continue/break)的最小可运行示例。
