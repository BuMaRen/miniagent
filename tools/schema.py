# 工具相关的数据类型定义，以及 ToolSchema 自动生成工具。
#
# ToolCall：LLM 返回的工具调用请求（定义在此处以避免 tools ↔ llm 循环依赖）
#   - id: str          # 工具调用的唯一 ID，用于将结果与请求对应
#   - name: str        # 工具名称
#   - arguments: str   # JSON 字符串，由调用方 json.loads() 解析
#
# ToolSchema：描述一个工具的元数据，用于向 LLM 声明工具能力
#   - name: str               # 工具名，模型调用时使用此名称
#   - description: str        # 工具功能描述，影响模型是否选择调用此工具
#   - parameters: dict        # JSON Schema 格式的参数定义
#
# 提供辅助函数 schema_from_func(func) -> ToolSchema：
#   - 从 Python 函数的类型注解和 docstring 自动生成 ToolSchema
#   - 利用 inspect 模块读取参数信息，利用 typing 模块处理类型映射
#   - 支持 Optional、list、dict 等常见类型到 JSON Schema 的转换

from pydantic.dataclasses import dataclass


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str  # JSON 字符串，由 ToolExecutor 负责解析


class ToolSchema:

    def __init__(self, name: str, description: str, parameters: dict):
        self._name = name
        self._description = description
        self._parameters = parameters

    @property
    def name(self):
        # 这个工具函数的名称，模型调用时使用此名称
        return self._name

    @property
    def description(self):
        # 这个工具函数的描述信息，通常从函数的 docstring 中提取
        return self._description

    @property
    def parameters(self):
        # 这个工具函数的参数，可以用参数名称（str）作为键检索到参数的类型和注释
        return self._parameters


class ParameterSchema:

    def __init__(self, parameter_type: str, description: str):
        self._parameter_type = parameter_type
        self._description = description

    @property
    def parameter_type(self):
        # 参数的类型，映射为 JSON Schema 的类型字符串（如 "string"、"integer"、"array"）
        return self._parameter_type

    @property
    def description(self):
        # 参数的描述信息，通常从函数的 docstring 中提取
        return self._description


def _parse_google_docstring(docstring: str) -> tuple[str, dict[str, str]]:
    """
    解析 Google 风格 docstring，返回 (函数描述, {参数名: 参数描述})。

    Google 风格格式：
        函数的整体描述文字。

        Args:
            param1: 参数1的描述。
            param2: 参数2的描述。
    """
    if not docstring:
        return "", {}

    lines = docstring.strip().splitlines()
    desc_lines = []
    param_descs = {}
    in_args = False

    for line in lines:
        stripped = line.strip()

        # 遇到 "Args:" 标记，切换到参数解析模式
        if stripped == "Args:":
            in_args = True
            continue

        if in_args:
            # 遇到其他不缩进的 section 标题（如 "Returns:"），退出参数解析
            if stripped and not line.startswith("    ") and not line.startswith("\t"):
                in_args = False
            elif ":" in stripped:
                # 格式为 "    param: 描述"，冒号前是参数名，后是描述
                param_name, _, param_desc = stripped.partition(":")
                param_descs[param_name.strip()] = param_desc.strip()
        else:
            desc_lines.append(line)

    return "\n".join(desc_lines).strip(), param_descs


def schema_from_func(func) -> ToolSchema:
    """
    从 Python 函数的类型注解和 Google 风格 docstring 自动生成 ToolSchema。
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

    # 从 docstring 中解析出函数整体描述和各参数描述
    description, param_descs = _parse_google_docstring(func.__doc__ or "")

    parameters = {}

    for name in sig.parameters:
        # 从 type_hints 里取这个参数的类型，找不到就默认当 str 处理
        param_type = type_hints.get(name, str)
        parameters[name] = ParameterSchema(
            parameter_type=_python_type_to_json_schema(param_type),
            # 从解析好的 param_descs 中按参数名取描述，找不到则为空字符串
            description=param_descs.get(name, ""),
        )

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
