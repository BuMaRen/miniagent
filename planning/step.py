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
    """Step represents a single step in a plan.

    Attributes:
        index (int): The step number (starting from 1).
        description (str): A natural language description of the step.
        status (str): The status of the step ("pending", "running", "done", "failed").
        result (str | None): A summary of the step's result (filled in after completion).
    """
    index: int
    description: str
    status: str = "pending"  # pending, running, done, failed
    result: str | None = None


@dataclass
class Plan:
    """Plan represents a sequence of steps to be executed.

    Attributes:
        steps (list[Step]): A list of Step objects representing the plan.
        current_index (int): The index of the current step being executed.
    Methods:
        is_complete() -> bool: Check if all steps are done.
        advance(result: str): Mark the current step as done and move to the next step.
        format() -> str: Format the plan into a readable string.
    """

    steps: list[Step]
    current_index: int = 0

    def is_complete(self) -> bool:
        """Check if the plan is complete.

        Returns:
            bool: True if all steps are done, False otherwise.
        """
        return all(step.status == "done" for step in self.steps)

    def advance(self, result: str):
        """Advance the plan to the next step.

        Args:
            result (str): The result of the current step.
        """
        if self.current_index < len(self.steps):
            self.steps[self.current_index].status = "done"
            self.steps[self.current_index].result = result
            self.current_index += 1

    def current_step(self) -> Step | None:
        """Get the current step being executed.

        Returns:
            Step | None: The current step, or None if the plan is complete.
        """
        if self.current_index < len(self.steps):
            return self.steps[self.current_index]
        return None

    def format(self) -> str:
        """Format the plan into a readable string.

        Returns:
            str: Formatted plan string.
        """
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
