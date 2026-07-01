# 内置文件系统工具集。
#
# 实现以下工具函数，文件末尾将它们收集到 fs_tools 列表导出：
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
# 文件末尾：
#   from tools.schema import schema_from_func
#   fs_tools = [(read_file, schema_from_func(read_file)), ...]
#
# 安全注意事项：
#   - 考虑路径遍历攻击，可选配置白名单根目录，拒绝访问白名单外路径


def read_file(path: str) -> str:
    """
    读取指定路径文件的文本内容，文件不存在时返回错误信息字符串。

    Args:
        path: 要读取的文件路径。
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return f"Error: File '{path}' not found."
    except Exception as e:
        return f"Error reading file '{path}': {str(e)}"


def write_file(path: str, content: str) -> str:
    """
    将内容写入指定路径，自动创建父目录，返回操作结果描述。

    Args:
        path: 要写入的文件路径。
        content: 要写入的文本内容。
    """
    import os

    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Successfully wrote to '{path}'."
    except Exception as e:
        return f"Error writing to file '{path}': {str(e)}"


def list_dir(path: str) -> str:
    """
    列出目录下的文件和子目录，返回格式化后的字符串。

    Args:
        path: 要列出内容的目录路径。
    """
    import os

    try:
        items = os.listdir(path)
        return "\n".join(items)
    except FileNotFoundError:
        return f"Error: Directory '{path}' not found."
    except Exception as e:
        return f"Error listing directory '{path}': {str(e)}"


def search_files(directory: str, pattern: str) -> str:
    """
    在目录下递归搜索匹配 glob pattern 的文件，返回路径列表字符串。

    Args:
        directory: 要搜索的根目录路径。
        pattern: glob 匹配模式，例如 "*.py" 或 "*.txt"。
    """
    import os
    import fnmatch

    matches = []
    for root, dirnames, filenames in os.walk(directory):
        for filename in fnmatch.filter(filenames, pattern):
            matches.append(os.path.join(root, filename))
    if not matches:
        return f"No files matching '{pattern}' found in '{directory}'."
    return "\n".join(matches)


from tools.schema import schema_from_func

fs_tools = [
    (read_file, schema_from_func(read_file)),
    (write_file, schema_from_func(write_file)),
    (list_dir, schema_from_func(list_dir)),
    (search_files, schema_from_func(search_files)),
]
