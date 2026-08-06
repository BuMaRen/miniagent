# 贡献指南

感谢你对 MiniAgent 感兴趣！在提交 Issue 或 PR 之前，请花几分钟阅读本指南。

## 项目定位

在动手之前，建议先读一遍 [README.md](README.md)，
理解框架层（`engine`/`agent`/`state`/`llm`/`tools`）与场景层（`scenarios/`）的边界：

- **框架层**的改动应保持场景无关，任何看起来像"为了某个场景而加"的字段/分支，通常说明设计错了地方。
- **场景层**的改动（新增/扩展场景）不需要动框架结构，只需要拼装既有原语、开发对应 ToolSet。

## 开发环境

```bash
git clone https://github.com/BuMaRen/miniagent.git
cd miniagent
pip install -r requirements.txt
```

框架层测试仅依赖标准库 `unittest`：

```bash
python3 -m unittest discover -s tests -t .
```

## 提交 Issue

- Bug 报告请附上复现步骤、期望行为与实际行为。
- 功能建议请先说明用例，尤其是"这属于框架层还是场景层"，方便判断是否符合项目定位。

## 提交 Pull Request

1. Fork 仓库，基于 `main` 创建分支（建议命名 `feat/xxx`、`fix/xxx`）。
2. 改动前先确认涉及范围：框架结构改动请附带设计理由；场景/ToolSet 改动尽量自包含。
3. 提交前本地跑一遍测试，新增功能请补充对应的单元测试。
4. Commit message 遵循 [Conventional Commits](https://www.conventionalcommits.org/)，例如：

   ```
   feat(engine): add retry policy to Loop primitive
   fix(state): correct patch merge for nested paths
   docs: update framework design doc section 8
   ```

5. PR 描述中说明改动动机（why）而不仅是改动内容（what），并关联相关 Issue。

## 代码风格

- Python 代码遵循项目现有风格，无强制 linter 配置时以可读性和与相邻代码一致为准。
- 避免为假设中的未来需求做设计；框架层的抽象改动请先在 Issue 中讨论。

## 许可

提交贡献即表示你同意你的代码以本项目的 [MIT License](LICENSE) 授权发布。
