"""ToolSchema 与从函数自动生成 schema。

ToolSchema 是工具对 LLM 的自描述(名称 + 说明 + 参数 JSON Schema),形态与
OpenAI function-calling 的 tool 定义对齐,便于直接下发给模型。
"""

from __future__ import annotations

import inspect
import re
import typing
from dataclasses import dataclass, field
from typing import Any, Callable

_TYPE_MAP: dict[Any, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}

_ARG_LINE_RE = re.compile(r"^(?P<name>\w+)\s*(?:\([^)]*\))?\s*:\s*(?P<desc>.*)$")


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
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def to_anthropic(self) -> dict[str, Any]:
        """转成 Anthropic tool-use 的 tool 定义结构"""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


def schema_from_func(func: Callable[..., Any]) -> ToolSchema:
    """从函数签名与 docstring 自动生成 ToolSchema。"""
    doc = inspect.getdoc(func) or ""
    description = doc.split("\n\n", 1)[0].strip() if doc else ""
    arg_docs = _parse_arg_docs(doc)

    hints = typing.get_type_hints(func)  # 解析字符串/延迟求值的注解为真实类型对象

    properties: dict[str, Any] = {}
    required: list[str] = []
    for name, param in inspect.signature(func).parameters.items():
        if param.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue
        prop: dict[str, Any] = {"type": _json_type(hints.get(name, param.annotation))}
        if name in arg_docs:
            prop["description"] = arg_docs[name]
        if param.default is inspect.Parameter.empty:
            required.append(name)
        else:
            prop["default"] = param.default
        properties[name] = prop

    parameters = {"type": "object", "properties": properties, "required": required}
    return ToolSchema(
        name=func.__name__, description=description, parameters=parameters
    )


def _json_type(annotation: Any) -> str:
    """把 Python 类型注解映射为 JSON Schema 的 type 字符串。"""
    if annotation is inspect.Parameter.empty:
        return "string"
    base = typing.get_origin(annotation) or annotation
    return _TYPE_MAP.get(base, "string")


def _parse_arg_docs(doc: str) -> dict[str, str]:
    """解析 Google 风格 docstring 的 Args 段,返回 {参数名: 说明}。"""
    lines = doc.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == "Args:")
    except StopIteration:
        return {}

    arg_docs: dict[str, str] = {}
    current: str | None = None
    for line in lines[start + 1 :]:
        if not line.strip():
            continue
        if not line[:1].isspace():
            break  # 遇到下一个顶格小节(如 Returns:),Args 段结束
        stripped = line.strip()
        m = _ARG_LINE_RE.match(stripped)
        if m:
            current = m.group("name")
            arg_docs[current] = m.group("desc").strip()
        elif current:
            arg_docs[current] += " " + stripped
    return arg_docs
