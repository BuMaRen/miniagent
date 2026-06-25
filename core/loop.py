# AgentLoop：agentic loop 的核心控制流，与 Agent 基类解耦。
#
# 职责：
#   - 实现标准 agentic loop：调用 LLM -> 判断是否有工具请求 -> 执行工具 -> 再次调用 LLM -> ...
#   - 维护最大循环深度（max_steps），超出时中断并返回
#   - 每轮调用前后触发 LifecycleHooks（参见 hooks/lifecycle.py）
#   - 循环结束条件：模型不再请求工具调用，或 max_steps 达到上限
#
# 设计原则：
#   - 不直接调用任何 provider SDK，通过 LLMClient 抽象层交互
#   - 工具调用完成后【不注入额外 user 消息】，直接将 tool 结果追加到 messages 后再次调用
#     （针对不够健壮的本地模型，可在 AgentConfig 中配置 force_continue_prompt 来注入提示）
#   - 返回值统一为 LoopResult 数据类，包含最终答案文本、调用轮次、工具调用列表
