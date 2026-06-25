# LifecycleHooks：Agent 生命周期各阶段的回调钩子，供框架使用者注入自定义逻辑。
#
# 定义以下回调（均为可选，默认为 no-op）：
#
#   on_turn_start(user_input: str)
#     每次用户输入进入 agentic loop 时触发
#
#   on_turn_end(answer: str)
#     loop 结束、模型给出最终答案时触发
#
#   on_before_tool(tool_name: str, arguments: dict) -> dict
#     工具执行前触发，返回值会替换原始 arguments（可用于参数校验/修改）
#
#   on_after_tool(tool_name: str, arguments: dict, result: str) -> str
#     工具执行后触发，返回值会替换原始 result（可用于结果过滤/格式化）
#
#   on_llm_request(messages: list[Message])   LLM 调用前触发（可用于日志/监控）
#   on_llm_response(response: LLMResponse)    LLM 响应后触发
#
# 实现方式：
#   - 使用 dataclass，每个字段都是 Callable | None，默认 None
#   - AgentLoop 在对应时机检查字段是否非 None，非 None 则调用
