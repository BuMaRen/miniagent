# 更新日志

本项目的版本记录遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 格式，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [未发布]

## [0.1.0] - 2026-08-06

### 新增
- 框架层：`engine`（工作流引擎）、`agent`（能力挂载层）、`state`（共享状态）、
  `llm`（LLM 抽象层）、`tools`（工具系统）。
- 控制流原语：`Sequence`、`Loop`、`ForEach`、`Checkpoint`、`Breaker`（提前终止）、
  `Continuer`（驱动 Loop 重开下一轮）。
- 场景层挂载点 `scenarios/`，含 `scenarios/example/`（测试用例设计工作流）示例场景。
- 场景开发指南 [`scenarios/development-guide.md`](scenarios/development-guide.md)。
- 开源合规文件：`LICENSE`（MIT）、`CONTRIBUTING.md`、`CODE_OF_CONDUCT.md`。

[未发布]: https://github.com/BuMaRen/miniagent/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/BuMaRen/miniagent/releases/tag/v0.1.0
