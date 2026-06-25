# AgentConfig：Agent 的全局配置数据类（推荐使用 dataclass 或 pydantic BaseModel）。
#
# 包含字段：
#   - model: str                   # 使用的模型名称
#   - max_steps: int               # agentic loop 最大深度，默认 10
#   - system_prompt: str           # 系统提示词
#   - force_continue_prompt: str   # 工具调用后注入的 user 提示（留空则不注入）
#                                  # 仅在对接本地小模型时需要打开
#   - temperature: float           # 采样温度
#   - timeout: int                 # 单次 LLM 调用超时（秒）
#
# 支持从环境变量或 .env 文件加载默认值（通过 python-dotenv）。
