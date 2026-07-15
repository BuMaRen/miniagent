"""ToolSchema 与从函数自动生成 schema。

ToolSchema 是工具对 LLM 的自描述(名称 + 说明 + 参数 JSON Schema),形态与
OpenAI function-calling 的 tool 定义对齐,便于直接下发给模型。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class ToolSchema:
    """一个工具的自描述。

    Attributes:
        name:        工具名(须唯一,LLM 以此指定调用)。
        description: 工具用途说明(取自函数 docstring 概述)。
        parameters:  参数的 JSON Schema(properties / required)。
    """

    name: str
    description: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)

    def to_openai(self) -> dict[str, Any]:
        """转成 OpenAI function-calling 的 tool 定义结构。"""
        # TODO: {"type": "function", "function": {name, description, parameters}}
        raise NotImplementedError


def schema_from_func(func: Callable[..., Any]) -> ToolSchema:
    """从函数签名与 docstring 自动生成 ToolSchema。

    实现指导:
      - name:        func.__name__。
      - description: docstring 的首段。
      - parameters:  用 inspect.signature 遍历参数,把 Python 类型注解映射为
                     JSON Schema 类型(str->string、int->integer、bool->boolean、
                     list->array、dict->object 等);无默认值的参数进 required。
      - 参数说明可从 docstring 的 Args 段解析补进各参数的 description。
    """
    # TODO: 用 inspect + typing 提取签名并组装 ToolSchema。
    raise NotImplementedError
