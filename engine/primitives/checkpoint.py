"""Checkpoint —— 人工断点原语(docs/framework-design.md §6.4)。

流程执行到这里暂停,等待外部输入(批准 / 修改意见 / 补充信息)后再继续。
引擎只提供"能暂停并恢复"这个能力;是否设置、设在哪里、恢复输入长什么样,
由场景方在 Workflow 定义里决定。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.context import RunContext


@dataclass
class Checkpoint:
    """一个可暂停/恢复的人工介入点。

    Attributes:
        name:                断点名称(如 "confirm_outline")。
        resume_input_schema: 恢复执行所需外部输入的契约(如 {"approved": bool, "note": str})。
        prompt:              给人工看的提示文案(可选)。
    """

    name: str
    resume_input_schema: Any | None = None
    prompt: str | None = None

    def run(self, ctx: RunContext, inputs: dict[str, Any]) -> dict[str, Any]:
        # TODO:
        #   1. 触发 on_checkpoint hook。
        #   2. 若 ctx.checkpoint_handler 存在:调用它获取外部输入,
        #      用 resume_input_schema 校验后,合并进 inputs 返回。
        #   3. 若无 handler(非交互运行):抛出 CheckpointPause,由宿主持久化
        #      当前状态、择机恢复(支持长时间挂起的异步流程)。
        raise NotImplementedError


class CheckpointPause(Exception):
    """在无同步 handler 时抛出,携带断点名与当前上下文,供宿主持久化后恢复。"""

    def __init__(self, checkpoint_name: str) -> None:
        super().__init__(f"workflow paused at checkpoint: {checkpoint_name}")
        self.checkpoint_name = checkpoint_name
