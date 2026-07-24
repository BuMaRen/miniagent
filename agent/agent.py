"""Agent —— Stage 的典型执行体(docs/framework-design.md §4)。

Agent 把 LLM、工具、工具集、记忆组装在一起,内部驱动一个 agentic loop
(模型思考 -> 调用工具 -> 观察结果 -> 继续,直到产出最终输出)来完成一个 Stage。
它对外暴露成 engine.stage.Executor 的签名 (ctx, inputs) -> outputs。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from agent.toolset import ToolSet
from agent.memory import ConversationMemory
from llm.client import LLMClient
from llm.message import Message
from tools.registry import ToolRegistry, default_registry
from tools.executor import ToolExecutor


@dataclass
class Agent:
    """一个可执行的智能体。

    Attributes:
        client:       LLM 客户端(见 llm/client.py)。
        memory:       对话记忆。
        registry:     工具注册表;默认复用 tools.registry.default_registry。
        executor:     工具执行器;未显式传入时在 __post_init__ 里按
                      ToolExecutor(self.registry) 构造——不能简单默认成
                      ToolExecutor(default_registry),否则当调用方自定义了
                      registry 却省略 executor 时,两者会分别操作不同的
                      ToolRegistry,导致 load_toolset() 注册的工具 executor
                      根本查不到。
        toolsets:       已加载的工具集列表。
        max_steps:    单次运行内 agentic loop 的最大步数,防止失控。
    """

    client: LLMClient
    memory: ConversationMemory
    registry: ToolRegistry = default_registry
    executor: ToolExecutor | None = None
    toolsets: list[ToolSet] = field(default_factory=list)
    max_steps: int = 12

    def __post_init__(self) -> None:
        # 防止用户使用了自定义 registry 却没传 executor,导致 executor 仍然使用默认 registry
        if self.executor is None:
            self.executor = ToolExecutor(self.registry)

    def load_toolset(self, toolset: ToolSet, mode: str = "append") -> None:
        """加载一个 ToolSet:把其工具注册进 registry。

        Args:
            toolset: 待加载工具集。
            mode:  "append" 保留已有工具(默认);"replace" 先清空再加载。
        """
        if mode == "replace":
            for loaded in self.toolsets:
                for name in loaded.tool_names():
                    self.registry.unregister(name)
            self.toolsets = []
        elif mode != "append":
            raise ValueError(f"未知的 mode: {mode!r}")

        for func, schema in toolset.tools:
            if not self.registry.register(schema.name, func, schema):
                raise ValueError(
                    f"加载 ToolSet {toolset.name!r} 失败:工具名 {schema.name!r} 已被注册"
                )
        self.toolsets.append(toolset)

    def run(self, ctx: "RunContext", inputs: dict[str, Any]) -> dict[str, Any]:
        """作为 Stage 的 executor 执行。

        约定实现(agentic loop):
          1. 把 inputs(含 State Store 注入的相关切片)组织成一条 user 消息入 memory。
          2. 循环最多 max_steps 次:
               resp = client.chat(memory.render(), tools=registry.schemas())
               若 resp 含 tool_calls:executor 逐个执行,结果作为 tool 消息回填 memory,继续。
               否则:视为最终回复,跳出循环。
          3. 解析最终回复为结构化 outputs(供 Stage 校验 output_schema)。
        """
        self.memory.append(Message(role="user", content=json.dumps(inputs, ensure_ascii=False)))

        resp = None
        for _ in range(self.max_steps):
            if self.memory.needs_compaction():
                self._compact()

            resp = self.client.chat(self.memory.render(), tools=self.registry.schemas() or None)
            self.memory.append(resp.message)

            if not resp.tool_calls:
                break
            for result in self.executor.execute_all(resp.tool_calls):
                self.memory.append(result)

        return _parse_output(resp.message.content if resp else None)

    def _compact(self) -> None:
        """触发一次记忆压缩:让 LLM 把较早消息总结成一段摘要,回写进 Memory。

        Memory 只负责判断"该不该压缩"与"压缩哪些消息安全"(见 agent/memory.py);
        "怎么总结"由这里决定,因为只有 Agent 同时持有 LLMClient。

        注意:compaction_candidates() 和 apply_compaction() 之间,self.memory
        不能被再次改动(比如 append 新消息)——apply_compaction 内部会重新算一次
        切分点,依赖"两次调用之间消息列表不变"才能保证重算结果与这里总结的
        candidates 对应。此处两次调用之间只做了一次同步的 client.chat 请求、
        不触碰 memory,这个前提成立;若以后要改成异步/并发触发压缩,需要连带
        改掉 apply_compaction 的"重算"设计(见 memory.py 对应注释)。
        """
        candidates = self.memory.compaction_candidates()
        if not candidates:
            return
        transcript = "\n".join(
            f"[{m.role}] {m.content or ''}" for m in candidates
        )
        prompt = (
            "请把以下对话历史压缩成一段简洁摘要,保留后续任务仍需要的关键事实与结论:\n\n"
            + transcript
        )
        resp = self.client.chat([Message(role="user", content=prompt)])
        self.memory.apply_compaction(resp.message.content or "")


def _parse_output(content: str | None) -> dict[str, Any]:
    """把最终 assistant 回复解析成结构化 outputs,供 Stage 的 output_schema 校验。

    约定 Agent 以 JSON 对象作为最终产出;若回复不是合法 JSON 对象(如纯文本
    回复),退化为 {"output": content} 包装成 dict,而不是让整个 run 失败。
    """
    if content:
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            return parsed
    return {"output": content}


from typing import TYPE_CHECKING  # noqa: E402

if TYPE_CHECKING:
    from engine.context import RunContext
