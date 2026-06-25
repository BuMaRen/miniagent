# AgentRuntime：记录 Agent 单次 run() 调用期间的完整运行时状态。
#
# 字段：
#   - turn: int                        当前是第几轮 LLM 调用
#   - plan: Plan | None                当前执行的任务计划
#   - tool_calls_log: list[dict]       所有工具调用记录（name, args, result, timestamp）
#   - start_time: datetime             本次 run() 开始时间
#   - final_answer: str | None         最终答案
#
# 功能：
#   - record_tool_call(name, args, result)   追加工具调用日志
#   - summary() -> str                       生成可读的执行摘要（用于调试或注入上下文）
#   - reset()                                重置状态，供下一次 run() 复用
#
# 注意：
#   - 此类只做数据持有和简单方法，不含业务逻辑
#   - 与 ConversationContext（messages 列表）是不同的概念：
#     ConversationContext 是 LLM 看到的对话历史，AgentRuntime 是框架内部的执行状态
