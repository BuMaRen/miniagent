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

from dataclasses import dataclass


@dataclass
class Step:
    index: int
    description: str
    status: str = "pending"  # pending, running, done, failed
    result: str | None = None


@dataclass
class Plan:
    steps: list[Step]
    current_index: int = 0

    def is_complete(self) -> bool:
        return all(step.status == "done" for step in self.steps)

    def advance(self, result: str):
        if self.current_index < len(self.steps):
            self.steps[self.current_index].status = "done"
            self.steps[self.current_index].result = result
            self.current_index += 1

    def format(self) -> str:
        formatted_steps = []
        for step in self.steps:
            status_symbol = {
                "pending": "[ ]",
                "running": "[~]",
                "done": "[x]",
                "failed": "[!]",
            }.get(step.status, "[ ]")
            formatted_steps.append(
                f"{status_symbol} Step {step.index}: {step.description}"
            )
        return "\n".join(formatted_steps)
