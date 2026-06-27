# ToolExecutor：工具调用的执行器，将 LLM 返回的 ToolCall 路由到实际函数。
#
# 功能：
#   - execute(tool_call: ToolCall) -> str
#       从 ToolRegistry 查找对应函数，解析 arguments（JSON 字符串 -> dict），
#       调用函数，将返回值序列化为字符串并返回
#
# 错误处理：
#   - 工具不存在：返回带错误信息的字符串（而非抛异常），让 LLM 有机会自我纠错
#   - arguments 解析失败：同上
#   - 工具执行抛出异常：捕获并格式化为错误字符串返回，记录 WARNING 日志
#
# 不应包含：
#   - 任何工具的具体实现逻辑（放在 tools/builtin/ 下）

from .schema import ToolCall
from .registry import ToolRegistry


class ToolExecutor:

    def __init__(self, tool_registry: ToolRegistry):
        self._tool_registry = tool_registry

    def execute(self, tool_call: ToolCall) -> str:
        """
        执行工具调用。

        1. 从 ToolRegistry 查找对应函数和 schema
        2. 解析 arguments（JSON 字符串 -> dict）
        3. 调用函数，捕获异常
        4. 将返回值序列化为字符串并返回
        """
        function, _ = self._tool_registry.get(tool_call.name)
        if function is None:
            return f"Error: Tool '{tool_call.name}' not found."

        try:
            import json

            args_dict = json.loads(tool_call.arguments)
        except json.JSONDecodeError as e:
            return f"Error: Failed to parse arguments for tool '{tool_call.name}': {str(e)}"

        try:
            result = function(**args_dict)
            return str(result)
        except Exception as e:
            import traceback

            tb_str = traceback.format_exc()
            return f"Error: Exception occurred while executing tool '{tool_call.name}': {str(e)}\n{tb_str}"
