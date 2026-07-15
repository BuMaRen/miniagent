# 故事圣经(Story Bible)数据结构设计

> 这是[框架设计(framework-design.md §5)](framework-design.md#5-state-store--通用共享状态接口)中 **State Store** 接口的一个场景实例:引擎只提供 `get/patch/append/slice` 的通用读写接口,字段语义由本文档定义。迁移到其他场景时,复用的是接口,重写的是这份 Schema。

故事圣经是小说生成工作流的共享状态,贯穿角色设计、大纲生成、逐章撰写、章节审校、全文统稿各阶段。它存在的目的是把"一致性"从"依赖模型记住全文"变成"读写一份结构化数据",从而在中短篇篇幅下也能可靠地避免前后矛盾。

## 设计原则

- **只记会被引用的事实**:不做百科全书式的世界观设定,只记录情节或人物一致性会用到的信息,避免状态膨胀。
- **增量更新**:每章撰写后只提交本章新增/变更的部分,而不是重写整份状态。
- **可切片读取**:撰写第 N 章时只取"本章涉及的角色/地点/伏笔"子集,而不是每次注入全量状态。

## 顶层结构

```yaml
story_bible:
  meta:
    title: string            # 可在立意阶段留空,后续补全
    logline: string
    theme: string             # 主题表达
    core_conflict: string
    structure_template: string  # 三幕式 / 起承转合 / 英雄之旅
    target_word_count: [min, max]

  characters:
    - id: string
      name: string
      role: protagonist | antagonist | supporting
      goal: string             # 该角色想要什么
      motivation: string        # 为什么想要
      flaw: string              # 弱点/内在障碍
      arc: string               # 从…到…的变化轨迹
      relationships:
        - target_id: string
          relation: string
      status_log:                # 随章节推进追加,不覆盖历史
        - after_chapter: int
          state: string          # 该角色在此时的状态/立场变化

  world:
    - id: string
      name: string
      description: string        # 只写情节会用到的规则/设定
      established_in_chapter: int

  timeline:
    - chapter: int
      event: string
      involved_characters: [character_id]

  foreshadowing:
    - id: string
      planted_in_chapter: int
      description: string
      payoff_chapter: int | null   # 尚未回收时为 null
      status: planted | resolved | dropped   # dropped 需在全文统稿阶段显式判定,不能悬空

  chapters:
    - index: int
      title: string
      beat_summary: string        # 大纲阶段产出的节拍描述
      draft_summary: string       # 撰写完成后的摘要,供后续章节引用
      status: planned | drafted | reviewed
```

## 各阶段的读写方式

| 阶段 | 写入 | 读取 |
|---|---|---|
| 角色与世界观设计(3.3) | `meta`、`characters` 初始值、`world` 初始值 | — |
| 大纲生成(3.4) | `chapters[*].beat_summary`、`foreshadowing` 计划(哪章埋/哪章回收) | `meta`、`characters` |
| 逐章撰写(3.6) | 本章 `draft_summary`、`characters[*].status_log` 增量、`timeline` 新增事件、`foreshadowing` 状态变更 | 本章相关的 `characters`、`world`、`foreshadowing`、上一章 `draft_summary` |
| 章节审校(3.8) | 修订后覆盖 `draft_summary`(如有变化) | 本章相关切片 + 已确立的 `timeline`,用于矛盾检测 |
| 全文统稿(3.9) | `foreshadowing[*].status` 终态(resolved/dropped) | 全量 `foreshadowing`,逐一核对是否都有归宿 |

## 示例(节选)

```yaml
characters:
  - id: char_01
    name: "苏昀"
    role: protagonist
    goal: "找到失踪的妹妹"
    motivation: "亏欠感——妹妹失踪那晚她本该在场"
    flaw: "习惯性回避直接冲突"
    arc: "从回避冲突 到 主动直面真相"
    status_log:
      - after_chapter: 3
        state: "得知妹妹失踪与父亲的旧债有关,开始怀疑父亲"

foreshadowing:
  - id: fs_01
    planted_in_chapter: 2
    description: "苏昀在父亲抽屉里发现一张没见过的当票"
    payoff_chapter: 7
    status: planted
```

## 与实现层的关系

本文档只定义数据结构,不假设具体的存储介质(内存对象/JSON 文件/数据库均可)。落地实现时,故事圣经应对应框架中通用 State Store 抽象的一个具体实例,便于未来其他场景复用同一套读写接口。
