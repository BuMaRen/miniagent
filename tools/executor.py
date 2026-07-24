"""ToolExecutor —— 工具调用的安全执行。

把 LLM 返回的 ToolCall 落到实处:按名查函数、校验/解包参数、执行、捕获异常,
把结果规整成可回填给模型的 tool 消息。
"""

from __future__ import annotations

from typing import Any

from llm.message import Message, ToolCall
from tools.registry import ToolRegistry, default_registry


class ToolExecutor:
    def __init__(self, registry: ToolRegistry = default_registry):
        self._registry = registry

    def execute(self, call: ToolCall) -> Message:
        """执行单个工具调用,返回 role="tool" 的结果消息。

        实现指导:
          1. func = registry.get(call.name)。
          2. 按 schema 校验 call.arguments,再以关键字参数调用 func。
          3. 用 try/except 包裹:出错时把异常信息作为工具结果返回(而非让整个
             agentic loop 崩溃),让模型有机会纠正。
          4. 把返回值序列化为字符串,组装成 Message(role="tool",
             tool_call_id=call.id, content=结果)。
        """
        try:
            func = self._registry.get(call.name)
            result = func(**call.arguments)
        except Exception as e:
            result = str(e)
        return Message(
            role="tool",
            tool_call_id=call.id,
            content=str(result),
        )

    def execute_all(self, calls: list[ToolCall]) -> list[Message]:
        """顺序执行多个工具调用,返回结果消息列表。

        注:如需并发,应确认这些工具无共享副作用/顺序依赖后再并行
        (既往调试中并发执行需要谨慎处理工具间的状态竞争)。
        """
        return [self.execute(c) for c in calls]
