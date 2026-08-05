"""Loop —— 迭代原语(docs/framework-design.md §6.2)。

**同一份输入，反复尝试到满意为止。** 和 ForEach 的关系是:ForEach 遍历 N 个不同
的元素、由数据耗尽决定停;Loop 反复处理同一份数据、由 body 里的 Continuer/
Breaker 节点决定停不停、重不重开。所以每一轮都从**同一份 inputs** 重新开始,
轮次之间不累积——这一点和 Sequence 也就只差"跑几次":Sequence 是 1 次,Loop 是
最多 max_iterations 次直到没人再要求重来。

一轮内部就是 Sequence 的规则:body 里的节点依次执行,上一个的 outputs 作为下一个
的 inputs。每个节点跑完之后,把它的 outputs 整块发布到游标
``_loop.<name>.last``(整块替换,不是合并),供 body[0] 用 reads 读到上一轮
为什么被打回(见 cursor_path)。

**"要不要重开一轮"由 body 里的 Continuer 节点决定,不是引擎自动问出来的。**
Continuer(见 engine/primitives/continuer.py)是放进 body 里的普通 Node,自带
`predicate(ctx, inputs) -> bool`;为真时跳过本轮 body 剩下的节点、从 body[0]
重开下一轮(相当于 Python 的 `continue`)。这与 Breaker 的关系完全对称:
Breaker 为真时结束整个 Loop(相当于 `break`);两者都通过异常
(LoopContinue / LoopBreak)通知 Loop,互不知晓对方存在,场景方在自己的
Workflow 定义里决定 Continuer/Breaker 放在 body 的哪个位置、判定逻辑读什么
状态——和"这一步该不该做"完全是同一种心智模型,不需要为"重开"专门学一套
隐式协议。

极性:body 跑完一轮、期间没有任何 Continuer/Breaker 触发 = 通过,Loop 到此
结束(不会自动再来一轮)。想要"反复跑到某个条件满足为止",场景方必须显式在
body 里放一个 Continuer,判定条件不满足时抛出 LoopContinue——这与 Python 里
`while` 循环"条件为真才继续"的直觉相反,是刻意的:Loop 的默认假设是"跑一轮就
该收尾",继续与否必须由场景方的判定逻辑主动争取,而不是引擎替场景方猜。

短路是白拿的:Continuer/Breaker 放在**某个节点之后**,前面的节点已经执行、
后面的节点不会执行——所以 ``body: [redraft, review, Continuer(...)]`` 里,
review 判定"还有用例待处理"时,下一轮会从 redraft 重新开始,不会拿一份还没
定案的草稿去问下一步。

**返回值只是"这一轮最后跑完的那个节点的 outputs(或触发 Continuer/Breaker 时
携带的 outputs)+ 一份 _loop 记账",本原语不做任何投影或裁剪。** 于是它可能
带着一些循环内部的中间字段按通道①流进循环后面的节点。这是刻意不管的:Loop
对外的正式接口是"body 里每个节点跑完后把 outputs 发布到
``_loop.<name>.last`` 这条状态路径";至于要不要把它的 outputs 当作后续节点的
inputs 来用,是场景方在自己的 Workflow 定义里决定的事,而每个节点真正需要
什么本来就该由它自己的 reads 声明。原语不替场景猜"哪些字段该留、哪些该扔"
——那是业务语义,不是控制流形状(见 §6.5 的判断标准)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from engine.stage import Node, StatePath
from engine.context import CheckpointRequest, RunContext
from engine.primitives.breaker import LoopBreak
from engine.primitives.continuer import LoopContinue


def loop_cursor_path(name: str) -> StatePath:
    """游标路径的拼接规则,独立成函数供场景代码复用(见 Loop.cursor_path)。

    场景代码需要在 Stage 的 `reads` 里引用某个 Loop 的游标时,应该调用这个函数而
    不是重新手写 `f"_loop.{name}.last"`——否则 Loop 的 `name` 与场景侧手写的路径
    字符串各写一遍,改名时容易漏改一处。
    """
    return f"_loop.{name}.last"


class OnExceed(str, Enum):
    """达到 max_iterations 仍未通过时的策略。"""

    ACCEPT_LAST = "accept_last_version"  # 接受最后一版,继续后续流程
    ESCALATE_TO_CHECKPOINT = "escalate_to_checkpoint"  # 升级为人工断点介入
    RAISE = "raise"  # 直接报错终止(禁止上层无限重试)


@dataclass
class Loop:
    """迭代:反复执行 body,直到某一轮完整跑完都没人要求重来,或跑满 max_iterations。

    Attributes:
        name:           循环名称(用于日志/断点定位,以及拼出游标路径)。
        body:           一轮要依次执行的节点(Sequence 的规则:上一个 outputs 流入
                        下一个 inputs)。想要反复跑多轮,须在 body 里放一个
                        engine.primitives.continuer.Continuer,由它的 predicate
                        决定"这一轮该不该判定为还要重来"。
        max_iterations: 最多跑几轮,防止死循环。
        on_exceed:      跑满 max_iterations 仍在被 Continuer 要求重来时的策略。
    """

    name: str
    body: list[Node] = field(default_factory=list)
    max_iterations: int = 3
    on_exceed: OnExceed = OnExceed.ESCALATE_TO_CHECKPOINT

    @property
    def cursor_path(self) -> StatePath:
        """游标:上一个节点的产出发布在这里,body[0] 可用 reads 读它。"""
        return loop_cursor_path(self.name)

    def run(self, ctx: RunContext, inputs: dict[str, Any]) -> dict[str, Any]:
        current: dict[str, Any] = dict(inputs)
        for i in range(self.max_iterations):
            if ctx.hooks and ctx.hooks.before_loop_iteration:
                ctx.hooks.before_loop_iteration(self.name, i)

            # 每轮都从同一份 inputs 重新开始(浅拷贝,免得节点对 inputs 的原地改写
            # ——如 Stage.run 往里塞 "state" ——跨轮泄漏)。轮次之间要传递的东西一律
            # 走游标,不走这里。
            current = dict(inputs)
            try:
                for node in self.body:
                    current = node.run(ctx, current)
                    self._publish(ctx, current)
            except LoopBreak as brk:
                # Breaker 判定优先:不再往下看,直接当作"本轮通过、循环立即结束"
                # 收尾(与 hooks 的 passed=True 语义一致)。
                if ctx.hooks and ctx.hooks.after_loop_iteration:
                    ctx.hooks.after_loop_iteration(self.name, i, True)
                return self._finish(ctx, brk.outputs, iterations=i + 1, exhausted=False)
            except LoopContinue:
                # Continuer 判定为真:跳过本轮 body 剩下的节点,进入下一轮(outer
                # for 循环的下一次 i);LoopContinue.outputs 与它触发前已发布到游标
                # 的 current 是同一份,不需要额外处理。
                if ctx.hooks and ctx.hooks.after_loop_iteration:
                    ctx.hooks.after_loop_iteration(self.name, i, False)
                continue

            # body 完整跑完、期间没有 Continuer/Breaker 触发 = 通过。
            if ctx.hooks and ctx.hooks.after_loop_iteration:
                ctx.hooks.after_loop_iteration(self.name, i, True)
            return self._finish(ctx, current, iterations=i + 1, exhausted=False)

        # 跑满 max_iterations、最后一轮仍被 Continuer 要求重来 -> 按 on_exceed 处理。
        if self.on_exceed == OnExceed.ACCEPT_LAST:
            return self._finish(
                ctx, current, iterations=self.max_iterations, exhausted=True
            )
        if self.on_exceed == OnExceed.ESCALATE_TO_CHECKPOINT:
            if ctx.checkpoint_handler is None:
                raise RuntimeError("Loop 超限,但 RunContext 未配置 checkpoint_handler")
            # 升级为人工裁决:current 是最后一轮最后执行到的那个节点的产出(短路时
            # 通常正是驳回它的评审意见,即"为什么走到这一步"的最直接说明);被评审
            # 的内容本身在 ctx.state 里,handler 需要时自己去读。
            request = CheckpointRequest(
                name=self.name,
                prompt=f"Loop {self.name} 超过 max_iterations={self.max_iterations} 仍未通过,请人工裁决。",
                context=current,
            )
            verdict = ctx.checkpoint_handler(request)
            return self._finish(
                ctx, verdict, iterations=self.max_iterations, exhausted=True
            )
        if self.on_exceed == OnExceed.RAISE:
            # 刻意不清游标:流程到此终止,留着它供事后诊断"最后一轮卡在哪"。
            raise LoopExceededError(
                f"Loop {self.name} 超过 max_iterations={self.max_iterations} 且未通过"
            )
        raise ValueError(f"未知的 on_exceed 策略: {self.on_exceed}")

    # -- 游标读写 -----------------------------------------------------------------

    def _publish(self, ctx: RunContext, outputs: dict[str, Any]) -> None:
        """把某个节点的产出发布到游标 —— 整块替换,不与上一次合并。

        写的是父路径 ``_loop.<name>``、值是 ``{"last": outputs}``:StateStore.patch
        对 dict 是**浅**合并,所以 last 这个 key 的值会被整体换掉,而不是和上一个
        节点的产出混在一起。这一点是正确性的关键——若合并,上一轮判定为真的那个
        字段会残留下来,下一轮的 body[0] 读到陈旧的产出。
        """
        ctx.state.patch(f"_loop.{self.name}", {"last": outputs})

    def _finish(
        self,
        ctx: RunContext,
        outputs: dict[str, Any],
        iterations: int,
        exhausted: bool,
    ) -> dict[str, Any]:
        """清游标并组装返回值。

        清游标:避免"上一轮的产出"泄漏给循环后面的节点,也避免它(可能是整章正文
        这种大对象)长期躺在持久化的状态快照里。只在"循环真的结束了"的路径上清——
        body 里任何节点抛异常穿过本方法(未捕获,直接冒泡)时不会清掉,那是故意的:
        WorkflowFailure 触发的续跑重新进入这个 Loop 时,body[0] 还要靠游标读回
        上一轮的评审意见。

        ``_loop`` 这个键让循环后面的节点(§6.2 里的 after_loop)能区分"是通过了"
        还是"跑满轮次被 on_exceed 放行的",而不必自己猜。
        """
        ctx.state.patch(f"_loop.{self.name}", {"last": None})
        return {
            **outputs,
            "_loop": {
                "name": self.name,
                "iterations": iterations,
                "exhausted": exhausted,
            },
        }


class LoopExceededError(RuntimeError):
    """Loop 超过 max_iterations 且策略为 RAISE 时抛出。"""
