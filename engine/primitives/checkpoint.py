"""Checkpoint —— 人工断点原语(docs/framework-design.md §6.4)。

流程执行到这里暂停,等待外部输入(批准 / 修改意见 / 补充信息)后再继续。
引擎只提供"能暂停并恢复"这个能力;是否设置、设在哪里、恢复输入长什么样,
由场景方在 Workflow 定义里决定。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.context import CheckpointRequest, RunContext
from state.schema import StateSchema


@dataclass
class Checkpoint:
    """一个可暂停/恢复的人工介入点。

    Attributes:
        name:                断点名称(如 "confirm_outline")。
        resume_input_schema: 恢复输入应满足的契约(一份 StateSchema,声明如
                             {"approved": bool, "note": str} 之类的字段)。handler
                             返回后由本原语委托 schema.validate 校验;None 表示不校验。
        prompt:              给人工看的提示文案(可选)。
    """

    name: str
    resume_input_schema: StateSchema | None = None
    prompt: str | None = None

    def run(self, ctx: RunContext, inputs: dict[str, Any]) -> dict[str, Any]:
        #   1. 触发 on_checkpoint hook。
        #   2. 若 ctx.checkpoint_handler 存在:把本断点封成 CheckpointRequest 交给它,
        #      拿回人工输入;用 resume_input_schema 校验(契约由引擎强制,而非信任
        #      业务侧 handler),通过后合并进 inputs 返回。
        #   3. 若无 handler(非交互运行):抛出 CheckpointPause,由宿主持久化
        #      当前状态、择机恢复(支持长时间挂起的异步流程)。
        if ctx.hooks and ctx.hooks.on_checkpoint:
            ctx.hooks.on_checkpoint(self.name)
        #   0. 恢复路径:挂起期间宿主已把人工输入放进 ctx.resume。若这份恢复点正是
        #      冲着本断点来的,就认领它(同样由引擎强制 schema 校验),并入 inputs 后
        #      清空 ctx.resume 继续——不再暂停,也不触发 handler。
        if ctx.resume is not None and ctx.resume.checkpoint_name == self.name:
            resume_input = ctx.resume.resume_input
            if self.resume_input_schema is not None:
                self.resume_input_schema.validate(resume_input)
            inputs.update(resume_input)
            ctx.resume = None
            return inputs
        if ctx.checkpoint_handler:
            # context=inputs:把流入本断点的产出(草稿/待裁决内容)一并交给 handler,
            # 否则人工只能看到 prompt 这句静态文案,看不到到底在评审什么。
            request = CheckpointRequest(name=self.name, prompt=self.prompt, context=inputs)
            resume_input = ctx.checkpoint_handler(request)
            if self.resume_input_schema is not None:
                self.resume_input_schema.validate(resume_input)
            inputs.update(resume_input)
            return inputs
        raise CheckpointPause(self.name)


class CheckpointPause(Exception):
    """在无同步 handler 时抛出,携带断点名与当前上下文,供宿主持久化后恢复。

    node_index / inputs 在抛出时为空,由外层 Workflow.run 捕获后回填(Checkpoint
    自身不知道它在顶层节点序列里的位置);宿主据这三项即可构造 ResumePoint。
    """

    def __init__(
        self,
        checkpoint_name: str,
        node_index: int | None = None,
        inputs: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(f"workflow paused at checkpoint: {checkpoint_name}")
        self.checkpoint_name = checkpoint_name
        self.node_index = node_index
        self.inputs = inputs
