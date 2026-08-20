"""Checkpoint —— 人工断点原语。

流程执行到这里,同步向外部(人工/审批系统)要一次输入,拿到答案后立刻继续。
是否设置、设在哪里、恢复输入长什么样,由场景方在 Workflow 定义里决定;"怎么去问"
则由场景方提供的 CheckpointHandler 决定(CLI input()、Web 表单、消息队列……)。

Checkpoint 本身**不提供**"没有 handler 时挂起整个进程、择日再续跑"的能力——
`ctx.checkpoint_handler` 是必需的,缺失就是一次配置错误,与任何其它节点缺少必要
依赖时的处理方式一样:直接报错,交由 `engine.workflow.Workflow.run` 的通用失败
路径包成 `WorkflowFailure` 冒泡给宿主(游标/inputs 回填、下次续跑重试这个节点,
这条能力仍然存在,只是不再是 Checkpoint 专属的暂停机制,见 WorkflowFailure)。
handler 自己想要"现在不答、留到以后"这种效果,可以在其内部直接抛出任意异常
(同样会被上述通用失败路径接住),不需要引擎为此单独开一条暂停通道。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from bumaren_agent_workflow.engine.context import CheckpointRequest, RunContext
from bumaren_agent_workflow.state.schema import StateSchema


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
        #   2. ctx.checkpoint_handler 是必需的:没有就是配置错误,直接报错(见模块
        #      docstring——不再有"无 handler 时挂起"这条路径)。
        #   3. 把本断点封成 CheckpointRequest 交给 handler,同步拿回人工输入;用
        #      resume_input_schema 校验(契约由引擎强制,而非信任业务侧 handler),
        #      通过后合并进 inputs 返回。
        if ctx.hooks and ctx.hooks.on_checkpoint:
            ctx.hooks.on_checkpoint(self.name)
        if ctx.checkpoint_handler is None:
            raise RuntimeError(
                f"Checkpoint {self.name!r} 需要 ctx.checkpoint_handler,但当前 RunContext 未配置"
            )
        # context=inputs:把流入本断点的产出(草稿/待裁决内容)一并交给 handler,
        # 否则人工只能看到 prompt 这句静态文案,看不到到底在评审什么。
        request = CheckpointRequest(name=self.name, prompt=self.prompt, context=inputs)
        resume_input = ctx.checkpoint_handler(request)
        if self.resume_input_schema is not None:
            self.resume_input_schema.validate(resume_input)
        inputs.update(resume_input)
        return inputs
