"""输入解析——纯函数,不需要 LLM。"""

from __future__ import annotations

from typing import Any

from engine.context import RunContext
from engine.stage import Stage

from scenarios.short.brief import parse_brief
from scenarios.short.nodes.common import BRIEF_PATH


def input_parsing_executor(ctx: RunContext, inputs: dict[str, Any]) -> dict[str, Any]:
    """校验用户设定并落进 State。

    inputs 就是 run.py 读进来的 brief.yaml。这里再调一次 parse_brief 而不是信任
    宿主:parse_brief 是幂等的(补过默认值的 brief 再解析一次结果不变),多跑
    一次的代价是零,换来的是"不管谁来驱动这个 Workflow,short_story.brief 都
    必然是一份合法的完整设定"。
    """
    brief = parse_brief({k: v for k, v in inputs.items() if k != "state"})
    return {BRIEF_PATH: brief}


def build_input_parsing_stage() -> Stage:
    return Stage(name="input_parsing", executor=input_parsing_executor, writes=[BRIEF_PATH])
