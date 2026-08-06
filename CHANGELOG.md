# 更新日志

本项目的版本记录遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 格式，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [未发布]

### 新增
- 框架层目录骨架：`engine`（工作流引擎）、`agent`（能力挂载层）、`state`（共享状态）、
  `llm`（LLM 抽象层）、`tools`（工具系统）。
- 四个控制流原语：`Sequence`、`Loop`、`ForEach`、`Checkpoint`，以及提前终止用的 `Breaker`。
- 场景层挂载点 `scenarios/`，含示例场景用于验证框架抽象。
- 项目文档：`docs/framework-design.md`（框架设计）、`docs/workflow-design.md`（工作流设计）、
  `docs/story-bible-schema.md`（状态 Schema）。
- 开源合规文件：`LICENSE`（MIT）、`CONTRIBUTING.md`、`CODE_OF_CONDUCT.md`。

## [0.1.0] - 2026-08-06

### 新增
- 项目初始版本：可复用 AI 工作流框架第一版。

[未发布]: https://github.com/BuMaRen/miniagent/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/BuMaRen/miniagent/releases/tag/v0.1.0
