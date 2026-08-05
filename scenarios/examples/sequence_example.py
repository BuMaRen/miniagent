"""Sequence 示例 —— 最简单的原语:按顺序跑,上一个的 outputs 就是下一个的 inputs。

没有循环、没有分支,`Sequence` 只做一件事:`A -> B -> C`。放在这里是给后面几个
更复杂的示例打底——Loop/ForEach 的一轮/一次迭代内部,遵守的正是同一条规则。

运行:python -m scenarios.examples.sequence_example
"""

from __future__ import annotations

from typing import Any

from engine.context import RunContext
from engine.primitives.sequence import Sequence
from engine.stage import Stage
from state.backends.memory import InMemoryStateStore


def build_add_stage(name: str, delta: int) -> Stage:
    """一个只做加法的纯函数节点:把 inputs["value"] 加上 delta。

    不读写 State(没有 reads/writes),数据完全走"上一个节点的 outputs 直接作为
    下一个节点的 inputs"这条通道——见 docs/framework-design.md §3.2 的"数据两条
    通道"说明,这是最省事、也最常见的一种。
    """

    def executor(ctx: RunContext, inputs: dict[str, Any]) -> dict[str, Any]:
        new_value = inputs["value"] + delta
        print(f"  [{name}] {inputs['value']} + {delta} = {new_value}")
        return {"value": new_value}

    return Stage(name=name, executor=executor)


def build_workflow() -> Sequence:
    return Sequence(
        name="add_pipeline",
        nodes=[
            build_add_stage("add_1", 1),
            build_add_stage("add_10", 10),
            build_add_stage("add_100", 100),
        ],
    )


def main() -> None:
    ctx = RunContext(state=InMemoryStateStore())
    seq = build_workflow()
    print("Sequence: add_1 -> add_10 -> add_100")
    outputs = seq.run(ctx, {"value": 0})
    print(f"最终结果: {outputs}")
    assert outputs == {"value": 111}


if __name__ == "__main__":
    main()
