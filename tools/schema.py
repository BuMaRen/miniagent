# ToolSchema：描述一个工具的元数据，用于向 LLM 声明工具能力。
#
# 字段：
#   - name: str               # 工具名，模型调用时使用此名称
#   - description: str        # 工具功能描述，影响模型是否选择调用此工具
#   - parameters: dict        # JSON Schema 格式的参数定义
#
# 提供辅助函数 schema_from_func(func) -> ToolSchema：
#   - 从 Python 函数的类型注解和 docstring 自动生成 ToolSchema
#   - 利用 inspect 模块读取参数信息，利用 typing 模块处理类型映射
#   - 支持 Optional、list、dict 等常见类型到 JSON Schema 的转换
