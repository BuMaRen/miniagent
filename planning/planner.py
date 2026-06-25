# Planner：将用户输入拆解为可执行的步骤列表。
#
# 功能：
#   - plan(user_input: str, context: str | None) -> Plan
#       调用 LLM，将 user_input 分解为若干有序步骤，返回 Plan 对象
#
# Prompt 设计要点：
#   - 让 LLM 以 JSON 格式返回步骤列表，便于结构化解析
#   - 注入 context（如上一轮答案摘要）帮助 LLM 了解当前状态
#   - 步骤数量有上限（从 AgentConfig.max_steps 读取）
#
# 可选功能 replan(plan, failed_step, error) -> Plan：
#   - 当某步骤失败时，根据失败原因重新规划剩余步骤
#
# 注意：
#   - Planner 使用的 LLM 调用是独立的（不影响 agentic loop 的 messages 列表）
