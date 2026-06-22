from dataclasses import dataclass, field
from typing import Any

@dataclass
class AgentState:

    depth: int = 0

    # per-turn data
    current_plan: list[str] = field(default_factory=list)
    tool_history: list[dict[str, Any]] = field(default_factory=list)

    # cross-turn data
    last_answer: str = ""

    def start_turn(self):
        self.depth = 0
        self.current_plan = []
        self.tool_history = []

    def set_plan(self, steps):
        self.current_plan = steps

    def record_tool(self, tool_name, args, result):
        """记录一次工具调用记录"""
        self.tool_history.append({
            "name": tool_name,
            "arguments": args,
            "result": result,
        })

    def finish_turn(self, answer):
        """完成所有工具调用，单次调用结束，记录最终回答"""
        self.last_answer = answer
        self.depth = 0

    def summary_for_user(self):
        lines = []
        if self.last_answer:
            lines.append(f"上一轮回答：{self.last_answer}")
        return "\n".join(lines)
