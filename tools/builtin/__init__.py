# 导出所有内置工具，供一键注册：
#   - fs_tools：文件系统相关工具列表
#   - web_tools：网络请求相关工具列表
#   - shell_tools：Shell 命令相关工具列表
#
# 使用方式：
#   from tools.builtin import fs_tools
#   for name, func in fs_tools:
#       registry.register(name, func)
