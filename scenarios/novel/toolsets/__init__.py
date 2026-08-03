"""本场景挂载给各 Stage 的 ToolSet。

按 docs/framework-design.md §4:ToolSet 只是数据(一组 function + schema)。
本子包下每个模块顶层定义的 ToolSet 实例(如 research.py 的 RESEARCH_TOOLSET)
会被 engine.scenario.Scenario.from_package 自动发现并登记,stages.yaml 里的
节点用 `tools: [名字]` 按名挂载,不需要在场景侧手写注册代码。
"""
