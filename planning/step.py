# Step 和 Plan：任务分解的数据结构。
#
# Step（dataclass）：
#   - index: int                        步骤编号（从 1 开始）
#   - description: str                  步骤描述（自然语言）
#   - status: Literal["pending", "running", "done", "failed"]
#   - result: str | None                步骤执行结果摘要（完成后填入）
#
# Plan：
#   - steps: list[Step]
#   - current_index: int                当前执行到第几步
#   - is_complete() -> bool             所有步骤都是 done 状态
#   - advance(result: str)              将当前步骤标记为 done 并推进到下一步
#   - format() -> str                   格式化为适合注入 prompt 的字符串
