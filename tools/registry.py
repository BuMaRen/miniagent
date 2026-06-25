# ToolRegistry：工具的注册与查找中心。
#
# 功能：
#   - register(name, func, schema)  注册一个工具（名称、可调用函数、Schema）
#   - get(name) -> (func, schema)   按名称查找工具
#   - schemas() -> list[ToolSchema] 返回所有注册工具的 Schema 列表，供 LLM 调用时传入
#
# 提供 @tool 装饰器（在此文件或 __init__.py 中定义）：
#   - 用法：@registry.tool 或 @tool（全局默认注册表）
#   - 自动调用 schema_from_func 生成 Schema 并注册
#   - 装饰后函数行为不变，仍可直接调用
#
# 注意：
#   - 工具名重复注册时应抛出明确异常，避免静默覆盖
