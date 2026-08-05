# scenarios/examples —— 框架原语速查手册

这不是一个真实场景(不像 `novel/`/`short/` 那样"解决一个具体问题"),是一份
**可以直接跑起来的框架用法参考**:数据怎么声明、四个控制流原语
(`Sequence`/`Loop`/`ForEach`/`Checkpoint`)加上 `Breaker` 怎么用,尤其把
`Loop` 的 `continue_when`("continue":还要再来一轮)与 `Breaker`("break":
提前结束循环)这两个容易混淆的概念拆开、并排讲清楚。

不挂任何 LLM/Agent/ToolSet:所有节点都是普通函数,不需要 API Key,秒开秒跑。
业务逻辑刻意写得很简单(加法、比大小),好让你一眼看穿"这一步在状态上做了
什么",不被真实业务细节分心——想看真实场景怎么挂 Agent/ToolSet,去看
`scenarios/novel/`、`scenarios/short/`,以及 [scenarios/development-guide.md](../development-guide.md)。

## 怎么跑

```bash
python -m scenarios.examples.run            # 全部示例跑一遍
python -m scenarios.examples.run --list      # 列出可选的示例名
python -m scenarios.examples.run --example loop   # 只跑一个

# 也可以直接跑单个文件,效果一样:
python -m scenarios.examples.loop_example
```

## 文件一览

| 文件 | 演示什么 |
|---|---|
| [`state_schema.py`](state_schema.py) | **数据声明**:`StateSchema` 的类型树写法——标量类型、`OneOf` 枚举、`ANY`、嵌套对象、同构列表;以及 `empty()`/`validate()`/`validate_path()`/`to_json_schema()`/`to_prompt_example()` 四个能力分别做什么。 |
| [`nodes.py`](nodes.py) | 本目录几个示例共用的节点定义(不挂 Agent,纯函数 executor)。 |
| [`sequence_example.py`](sequence_example.py) | `Sequence`:最简单的原语,`A -> B -> C`,上一个的 outputs 就是下一个的 inputs。 |
| [`loop_example.py`](loop_example.py) | **`Loop` /"continue"**:同一份输入反复跑 body,直到 `continue_when` 不再为真;外加 `on_exceed` 的三种策略(`ACCEPT_LAST`/`RAISE`/`ESCALATE_TO_CHECKPOINT`)分别演示一遍。 |
| [`foreach_example.py`](foreach_example.py) | `ForEach`:对列表里的每个元素重复跑一遍 body,由数据耗尽决定停,不是判定决定停。 |
| [`breaker_example.py`](breaker_example.py) | **`Breaker` /"break"**:predicate 为真时立刻终止最近的外层循环,后面的元素完全不会被碰。 |
| [`checkpoint_example.py`](checkpoint_example.py) | `Checkpoint`:人工断点单独使用,以及放进 `Loop.body` 末尾和"continue"组合成"AI 先挡、通过后人工再把关"。 |
| [`combined_example.py`](combined_example.py) | **`continue` + `break` 同框**:`ForEach` 遍历任务,每项内部用 `Loop` 反复谈判(continue),谈完定稿后用 `Breaker` 检查全局配额、够了就整批停止(break)。 |
| [`run.py`](run.py) | 统一入口,见上方"怎么跑"。 |

## `continue` 和 `break` 到底是谁负责

这是这份示例最想讲清楚的一件事,框架里没有名叫 `continue`/`break` 的原语,但
两个既有原语分别精确对应这两种语义。两者的判定函数现在是**同一种签名风格**——
都是 `(ctx, outputs/inputs) -> bool`,不是状态路径字符串,区别在"谁来调用它"和
"触发之后影响多大":

| Python 类比 | 框架原语 | 谁来调用、对着什么求值 | 影响范围 |
|---|---|---|---|
| `continue`(本轮到此为止,回到循环顶部重来一轮) | `Loop` 的 `continue_when` | `Loop` 自己:body 里**每个**节点跑完后,把它的 outputs 交给这个谓词求值一次 | 只影响**当前这个 Loop**,重开的是同一个 body、同一份输入 |
| `break`(立刻跳出整个循环) | `Breaker` | 场景方显式放进 `body` 里的一个 Node:轮到它执行时,把 `predicate(ctx, inputs)` 求值一次 | 终止**最近的外层** `Loop`/`ForEach`,循环外的东西该干嘛干嘛 |

两者的判定时机也不同:`continue_when` 只能问"刚跑完的这个节点算不算过"这一个
固定问题(引擎侧极性固定为"真 = 还要重开一轮",但谓词内部想用什么字段、要不要
取反是场景自己的事);`Breaker` 的 `predicate` 可以是任意条件,和"这一轮/这一项
算不算过"完全无关(比如本例里的"全局配额是否已满")。两者可以在同一个 `body`
里共存、互不知晓对方存在——`combined_example.py` 就是这个组合的完整演示。

## 和 `docs/framework-design.md` 的关系

这份示例是"看得懂代码怎么跑"的补充,不是概念定义的来源——四个原语的完整
设计意图、取舍理由,以本项目的 [docs/framework-design.md](../../docs/framework-design.md)
§6 为准;`Breaker` 的设计说明见 [engine/primitives/breaker.py](../../engine/primitives/breaker.py)
模块开头的 docstring。想知道"怎么把这些原语拼成一个真实场景",看
[scenarios/development-guide.md](../development-guide.md)。
