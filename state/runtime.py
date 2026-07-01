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

from dataclasses import dataclass
from datetime import datetime

from planning.step import Plan


@dataclass
class AgentRuntime:
    """AgentRuntime holds the complete runtime state of a single run() call of the Agent.

    Attributes:
        turn (int): The current turn number of the LLM call.
        plan (Plan | None): The current task plan being executed.
        tool_calls_log (list[dict]): A log of all tool calls (name, args, result, timestamp).
        start_time (datetime): The start time of the current run().
        final_answer (str | None): The final answer of the run().
    Methods:
        record_tool_call(name, args, result): Appends a tool call log entry.
        summary() -> str: Generates a readable summary of the runtime state.
        reset(): Resets the runtime state for the next run.
    """

    turn: int = 0
    plan: Plan = None
    tool_calls_log: list[dict] = None
    start_time: datetime = None
    final_answer: str = None

    def record_tool_call(self, name: str, args: dict, result: str):
        """Record a tool call in the runtime state.

        Args:
            name (str): The name of the tool.
            args (dict): The arguments passed to the tool.
            result (str): The result returned by the tool.
        """
        self.tool_calls_log.append(
            {
                "name": name,
                "args": args,
                "result": result,
                "timestamp": datetime.now().isoformat(),
            }
        )

    def summary(self) -> str:
        """Generate a readable summary of the runtime state.

        Returns:
            str: A summary of the runtime state.
        """
        summary_lines = [
            f"AgentRuntime Summary:",
            f"  Turn: {self.turn}",
            f"  Start Time: {self.start_time.isoformat()}",
            f"  Plan: {self.plan.steps if self.plan else 'None'}",
            f"  Tool Calls Log: {len(self.tool_calls_log)} calls",
            f"  Final Answer: {self.final_answer if self.final_answer else 'None'}",
        ]
        return "\n".join(summary_lines)

    def reset(self):
        """Reset the runtime state for the next run."""
        self.turn = 0
        self.plan = None
        self.tool_calls_log = []
        self.start_time = datetime.now()
        self.final_answer = None
