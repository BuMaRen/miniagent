"""本场景挂载给各 Stage 的 ToolSet。

按 docs/framework-design.md §4:ToolSet 只是数据(一组 function + schema)。
本子包下每个模块顶层定义的 ToolSet 实例(如 research.py 的 RESEARCH_TOOLSET)
由 scenarios/novel/nodes/ 下对应节点的模块直接 import 使用(见
agent.make_agent 的 toolsets 参数),不需要额外的注册/发现机制。
"""
