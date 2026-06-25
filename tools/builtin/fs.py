# 内置文件系统工具集。
#
# 实现以下工具函数，每个函数使用 @tool 装饰器注册：
#
#   read_file(path: str) -> str
#     读取指定路径文件的文本内容，文件不存在时返回错误信息字符串
#
#   write_file(path: str, content: str) -> str
#     将内容写入指定路径，自动创建父目录，返回操作结果描述
#
#   list_dir(path: str) -> str
#     列出目录下的文件和子目录，返回格式化后的字符串
#
#   search_files(directory: str, pattern: str) -> str
#     在目录下递归搜索匹配 glob pattern 的文件，返回路径列表字符串
#
# 安全注意事项：
#   - 考虑路径遍历攻击，可选配置白名单根目录，拒绝访问白名单外路径
