# Agent 落地标准：Planner 与 State

> 目标：保留生产级 Agent 最核心的两个模块，去掉可选优化，
> 让你能从零实现、跑通、并理解每个设计决策背后的原因。

---

## Planner

### 职责

把一句用户意图拆成 **有序的、可执行的步骤列表**。
Planner 只负责"拆"，不负责"做"——它不调用工具，不维护历史，不知道有哪些工具可用。

### 必须实现的能力

**1. 无状态调用**

每次调用都是独立的 API 请求，不携带上下文历史。
输入只有两样东西：用户意图 + 上一轮的结论摘要（可选）。

```
plan(user_input: str, context: str = "") -> list[str]
```

**2. 结构化输出**

必须输出可遍历的列表，不能是自然语言段落。
强制手段：在 system prompt 里要求模型只输出 JSON，用 `json.loads()` 解析。

**3. 失败时不崩溃**

解析失败、网络超时、模型拒绝时，返回 `[user_input]` 作为兜底。
Planner 是可选的优化层，它的失败不能中断 Agent 主循环。

**4. 步骤数量上限**

硬性截断，防止模型输出过多步骤。生产经验值：**5 步**够用，超过说明任务需要拆分成多个 Agent。

### 关键约束

| 约束 | 原因 |
|---|---|
| system role 放规划指令，user role 放用户意图 | system 优先级最高，防止用户输入覆盖格式要求 |
| temperature = 0 | 规划要确定性，随机性会让同一任务规划出不同步骤 |
| 不能在 steps 里写工具名或参数 | Steps 是意图，不是调用；工具选择是 Executor 的职责 |
| context 追加在 system prompt 末尾，而非独立 user 消息 | 防止模型把历史上下文误认为当前任务的一部分 |

---

## State

### 职责

作为 Agent 的"工作台"，承担两件事：
1. **轮内**：记录当前这轮的中间过程（计划、工具调用记录、递归深度）
2. **跨轮**：把上一轮的结论传递给下一轮的 Planner

### 字段分类——最重要的设计决策

所有字段必须明确归属两个生命周期之一，这是 State 设计的核心原则：

```
per-turn   每轮开始时重置    current_plan, tool_history, depth
cross-turn 跨轮保留          last_answer, context
```

判断方法：下一轮对话还需要这个数据吗？需要 → cross-turn，不需要 → per-turn。

### 必须实现的方法

**按 Agent 生命周期排序，顺序不可乱：**

```
start_turn(user_input)
    ↓
set_plan(steps)
    ↓
record_tool(name, args, result)  × N
    ↓
finish_turn(answer)
    ↓
summary_for_user()  → 传给下一轮 Planner
```

**`start_turn(user_input)`**
- 重置所有 per-turn 字段
- 保留所有 cross-turn 字段（它们是 Planner 感知历史的来源）
- 必须是每轮第一个调用

**`set_plan(steps)`**
- 将 Planner 输出写入 State
- 存在 State 而非直接传参的原因：Executor 的各个阶段都可能需要读取计划，单一数据源避免重复传参

**`record_tool(name, args, result)`**
- 每次工具返回后**立即**追加，不能批量补记
- 原因：Agent 递归调用自身时（工具触发下一轮），State 里必须已有本次记录

**`finish_turn(answer)`**
- 将最终回答持久化到 cross-turn 字段
- 只在模型不再调用工具、直接返回最终答案时调用
- 过早调用会把中间结果错误地写入跨轮记忆

**`summary_for_user() -> str`**
- 把 cross-turn 字段序列化成**简短的自然语言**，注入下一轮 Planner 的 context
- 只序列化结论，不序列化原始工具输出
- 第一轮没有历史时返回空字符串，Planner 跳过注入

### 关键约束

**无限循环防护（depth 熔断器）**

每次进入工具调用 depth +1，超过 max_depth 时强制退出，不再递归。
`start_turn()` 和 `finish_turn()` 都要归零 depth——两处归零是双重保险，不是重复代码：
- `start_turn` 处理"上一轮异常退出、depth 未重置"的情况
- `finish_turn` 处理"正常结束但未触发下一轮"的情况

**可变字段的默认值**

list 和 dict 类型的字段不能写 `= []` 或 `= {}`，必须用工厂函数：

```python
# 错误：所有实例共享同一个列表对象
tool_history: list = []

# 正确：每次实例化生成独立对象
tool_history: list = field(default_factory=list)
```

---

## 两者如何协作

```
用户输入
  │
  ▼
state.start_turn()
  │
  ▼
planner.plan(user_input, state.summary_for_user())
  │
  ▼
state.set_plan(steps)
  │
  ▼
[Executor 循环]
  ├─ 调用工具 → state.record_tool()
  └─ 无工具调用 → state.finish_turn(answer)
                          │
                          ▼
                   下一轮 planner.plan(..., state.summary_for_user())
```

---

## 暂时不需要实现的（学完核心再加）

| 能力 | 为什么先跳过 |
|---|---|
| 重规划（re-planning） | 需要先跑通单次规划再考虑失败恢复 |
| State 持久化 | 内存级足够验证逻辑，持久化是工程问题 |
| 长对话 token 压缩 | 短任务不会触发，实现前先理解 token 预算概念 |
| 并行执行 steps | 需要先理解串行流程再引入并发复杂度 |
