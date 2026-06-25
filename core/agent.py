# Agent 基类，框架使用者继承此类来创建自己的 Agent。
#
# 职责：
#   - 持有 LLMClient、ToolRegistry、Memory、Planner、AgentState 等核心组件的引用
#   - 提供 run(user_input: str) 公共入口，内部委托给 AgentLoop 执行
#   - 提供 install_tool(name, func) 方法，允许动态注册工具
#   - 提供 on_before_tool / on_after_tool hook 扩展点（可选重写）
#
# 不应包含：
#   - 任何与具体 LLM provider 耦合的代码
#   - loop 控制流逻辑（放在 loop.py）
#   - 工具执行逻辑（放在 tools/executor.py）
