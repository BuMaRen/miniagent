"""ForEach —— 遍历子流程原语(docs/framework-design.md §6.3)。

对某个列表状态字段中的每个元素,重复执行同一段子流程,且各次执行共享同一个
State Store 实例,从而保持连贯(小说里的"逐章撰写"就是
ForEach(chapters, body=Loop(draft, review, revise)))。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.stage import Node, StatePath
from engine.context import RunContext


@dataclass
class ForEach:
    """对列表中每个元素执行 body。

    Attributes:
        name:        节点名称。
        items_path:  从 State Store 取待遍历列表的路径(如 "story_bible.chapters")。
        body:        对每个元素执行的子流程(Stage / Loop / Sequence 均可)。
        item_key:    注入 body inputs 时,当前元素使用的键名(默认 "item")。
        index_key:   当前下标使用的键名(默认 "index")。
    """

    name: str
    items_path: StatePath
    body: Node
    item_key: str = "item"
    index_key: str = "index"

    def run(self, ctx: RunContext, inputs: dict[str, Any]) -> dict[str, Any]:
        # TODO:
        #   1. items = ctx.state.get(self.items_path)
        #   2. for i, item in enumerate(items):
        #        body.run(ctx, {**inputs, index_key: i, item_key: item})
        #      —— 各轮共享 ctx.state,保证连贯性;body 内部按需切片读取相关状态。
        #   3. 支持从中断处恢复(结合 Checkpoint):记录已完成的下标。
        #   返回汇总信息(如已处理数量),正文类结果通常已写入 ctx.state。
        raise NotImplementedError
