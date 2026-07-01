# 内置 Shell 工具集。
#
# 实现以下工具函数：
#
#   run_command(command: str, timeout: int | None) -> str
#     在子进程中执行 shell 命令，返回 stdout + stderr 合并的字符串
#     timeout 默认 30 秒，超时后强制终止并返回超时错误
#     返回格式包含 exit_code、stdout、stderr
#
# 安全注意事项（重要）：
#   - 默认禁用此工具，需在 AgentConfig 中显式开启
#   - 可配置命令黑名单（rm -rf、dd 等危险命令）
#   - 考虑使用沙箱（Docker、firejail）隔离执行环境
#   - 生产环境中应记录所有执行的命令到审计日志
