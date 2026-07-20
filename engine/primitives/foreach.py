"""ForEach —— 数据驱动的重复执行原语(docs/framework-design.md §6.3)。

把经典 for-each 循环搬到编排层::

    for (index = 0; index < len(items); index++) { body }

本原语**只负责"重复"这一件事**,不负责"连贯性"。连贯性(第 N 轮看到前
N-1 轮的产物)是 body 里各 Stage 对共享 StateStore 做 reads/writes 的自然
结果,不是循环的职责——所以这里没有、也不需要 shared_state / 累积量之类的
东西。

循环每轮做三步:
    - condition:index < len(items)?  —— 还要不要再来一轮。
    - bind:     把 items[index] 发布到游标 item_path —— body 用 reads 读它。
    - advance:  index++              —— 唯一决定"下一轮是谁"的地方。

而 body 每轮干活时,通过它自己的 reads 读到当前元素(iterator 发布的 item)、
读到前文状态,通过 writes 写回产出——和任何一个普通 Stage 完全一样。"当前元素
怎么喂给 body"这个老问题,就此归位成一条普通的 reads/writes,而非塞进 inputs
的魔法键。

纯声明式:整个节点由 items_path / body / 两个游标路径描述,可从 YAML 直接拼出
(见 Workflow.from_spec),不含任何运行期回调。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.stage import Node, StatePath
from engine.context import RunContext


@dataclass
class ForEach:
    """for-each:对 items_path 列表中的每个元素执行一遍 body。

    Attributes:
        name:       节点名称(同时用于生成默认游标路径,隔离嵌套 ForEach)。
        items_path: 待遍历列表的状态路径(如 "story_bible.chapters")。
        body:       每轮执行的子流程(Stage / Loop / Sequence 均可)。
        index_path: 游标——当前下标存放的状态路径。默认 f"_foreach.{name}.index"。
                    它同时是**恢复点**:从 Checkpoint 快照续跑时会接着这个下标走。
        item_path:  游标——当前元素发布到的状态路径。body 用 reads=[item_path] 读它。
                    默认 f"_foreach.{name}.item"。
    """

    name: str
    items_path: StatePath
    body: Node
    index_path: StatePath | None = None
    item_path: StatePath | None = None

    def run(self, ctx: RunContext, inputs: dict[str, Any]) -> dict[str, Any]:
        index_path = self.index_path or f"_foreach.{self.name}.index"
        item_path = self.item_path or f"_foreach.{self.name}.item"

        items = ctx.state.get(self.items_path, default=[]) or []

        # init:游标缺省从 0 开始;若状态里已有值(从 Checkpoint 快照恢复),
        #       则接着那个下标续跑 —— 恢复能力"免费"来自游标本身存在 State 里。
        if ctx.state.get(index_path, default=None) is None:
            ctx.state.patch(index_path, 0)

        count = 0
        # condition:index < len(items)
        while ctx.state.get(index_path, 0) < len(items):
            i = ctx.state.get(index_path, 0)

            # bind:把当前元素发布到游标,body 用普通 reads 读取它。
            ctx.state.patch(item_path, items[i])

            if ctx.hooks and ctx.hooks.before_loop_iteration:
                ctx.hooks.before_loop_iteration(self.name, i)

            # body 各轮共享 ctx.state(连贯性由此而来);inputs 每轮给一份浅拷贝,
            # 避免 Stage.run 对 inputs 的原地改写跨轮泄漏。
            self.body.run(ctx, dict(inputs))

            if ctx.hooks and ctx.hooks.after_loop_iteration:
                ctx.hooks.after_loop_iteration(self.name, i, True)

            # advance:index++ —— 唯一改变"下一轮是谁"的地方。
            ctx.state.patch(index_path, i + 1)
            count += 1

        # 清理游标,避免"当前元素"泄漏给后续节点。
        ctx.state.patch(item_path, None)
        return {"iterations": count, "items_path": self.items_path}
