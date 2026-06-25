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

from dataclasses import dataclass


@dataclass
class ToolSchema:
    # 这个工具函数的名称，模型调用时使用此名称
    name: str
    # 这个工具函数的描述信息，通常从函数的 docstring 中提取
    description: str
    # 这个工具函数的参数，可以用参数名称（str）作为键检索到参数的类型和注释
    parameters: dict


@dataclass
class ParameterSchema:
    # 参数的类型，映射为 JSON Schema 的类型字符串（如 "string"、"integer"、"array"）
    parameter_type: str
    # 参数的描述信息，通常从函数的 docstring 中提取
    description: str


def schema_from_func(func) -> ToolSchema:
    """
    从 Python 函数的类型注解和 docstring 自动生成 ToolSchema。
    """
    import inspect
    from typing import get_type_hints

    # inspect.signature 解析函数签名，返回一个 Signature 对象。
    # sig.parameters 是 {参数名: Parameter对象} 的有序字典。
    # 例如 def read_file(path: str, encoding: str) 会得到：
    #   {"path": <Parameter>, "encoding": <Parameter>}
    sig = inspect.signature(func)

    # get_type_hints 读取函数的类型注解，返回 {参数名: 类型} 的字典。
    # 比 param.annotation 更可靠，能处理字符串形式的注解（如 "list[str]"）。
    # 例如：{"path": str, "encoding": str, "return": str}
    type_hints = get_type_hints(func)

    parameters = {}

    for name, param in sig.parameters.items():
        # 从 type_hints 里取这个参数的类型，找不到就默认当 str 处理
        param_type = type_hints.get(name, str)
        parameters[name] = ParameterSchema(
            parameter_type=_python_type_to_json_schema(param_type),
            # param.annotation 是参数上标注的类型对象本身（如 str 这个类）。
            # 普通类型没有 __doc__，所以这里实际上几乎总是拿到 None 或空字符串。
            # 更实用的做法是从 docstring 里按参数名解析描述（此处留作改进点）。
            description=(
                param.annotation.__doc__
                if param.annotation != inspect.Parameter.empty
                else ""
            ),
        )

    # func.__doc__ 就是函数的 docstring，即三引号字符串。
    # 没写 docstring 时为 None，用 "" 兜底。
    description = func.__doc__ or ""

    # func.__name__ 是函数名字符串，例如 "read_file"
    return ToolSchema(
        name=func.__name__, description=description, parameters=parameters
    )


def _python_type_to_json_schema(py_type):
    """
    将 Python 类型映射为 JSON Schema 类型字符串。
    """
    import typing

    # 基础类型直接映射
    if py_type == str:
        return "string"
    elif py_type == int:
        return "integer"
    elif py_type == float:
        return "number"
    elif py_type == bool:
        return "boolean"
    # list 和 list[str] 这类泛型写法不同：
    #   - list        → py_type == list 为 True
    #   - list[str]   → py_type.__origin__ == list 为 True（__origin__ 是泛型的原始类型）
    elif py_type == list or getattr(py_type, "__origin__", None) == list:
        return "array"
    elif py_type == dict or getattr(py_type, "__origin__", None) == dict:
        return "object"
    # Optional[T] 本质是 Union[T, None]，__origin__ 是 Union。
    # __args__ 是 Union 包含的所有类型的元组，例如 Optional[str] 的 __args__ == (str, NoneType)
    elif getattr(py_type, "__origin__", None) is typing.Union:
        # 过滤掉 NoneType，只留实际类型
        types = [t for t in py_type.__args__ if t is not type(None)]
        if len(types) == 1:
            # Optional[T] → 递归处理 T
            return _python_type_to_json_schema(types[0])
        else:
            # Union[str, int] 等多类型情况，无法精确映射，退回 string
            return "string"
    else:
        return "string"
