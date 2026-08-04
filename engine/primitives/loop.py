"""Loop —— 迭代原语(docs/framework-design.md §6.2)。

**同一份输入，反复尝试到满意为止。** 和 ForEach 的关系是:ForEach 遍历 N 个不同
的元素、由数据耗尽决定停;Loop 反复处理同一份数据、由一个谓词决定停。所以每一轮
都从**同一份 inputs** 重新开始,轮次之间不累积——这一点和 Sequence 也就只差
"跑几次":Sequence 是 1 次,Loop 是最多 max_iterations 次直到谓词说"够了"。

一轮内部就是 Sequence 的规则:body 里的节点依次执行,上一个的 outputs 作为下一个
的 inputs。每个节点跑完之后做两件事:

  1. 把它的 outputs 整块发布到游标 ``_loop.<name>.last``(整块替换,不是合并);
  2. 读 ``continue_when`` 指向的状态路径,真 -> 本轮到此为止、从 body[0] 重开一轮。

第 2 条就是"是非器":引擎只做一次 ``ctx.state.get(path)`` 取真假,**不认识任何业务
字段名**(既没有 passed 也没有 feedback),更不需要表达式语言或场景侧的谓词回调。
路径缺失时 get 返回 None、判为假,所以 body 里那些不产出判定字段的节点(比如
producer)不会误触发重开一轮。

极性是固定的:**真 = 还要再来一轮**。所以被读的那个字段要朝着"还得改"为真去命名
(如 needs_revision),而不是 passed —— 裸路径读真假没有取反的余地,这是刻意的:
一旦支持取反就得引入表达式语言。

第 1 条的游标同时解决"下一轮怎么知道上一轮为什么没过":body[0] 用普通的
``reads=["_loop.<name>.last"]`` 就能读到上一个节点的产出(通常正是驳回它的那份
评审意见)。手法与 ForEach 发布 ``_foreach.<name>.item`` 完全一致——跨轮次要传的
东西走保留状态路径,不走"merge 进 inputs"。整块替换而非合并很关键:否则上一轮的
判定字段会残留到下一轮,是非器读到陈旧的真值就会永远重开。

短路是白拿的:判定放在**每个节点之后**而不是整条 body 之后,所以
``body: [outline_generation, outline_critic, confirm_outline]`` 里 AI 评审判否时,
后面的人工确认根本不会执行——不必拿一份 AI 都没过的草稿去打扰人。这正是它能取代
场景侧手写 ReviewChain 的原因。

**返回值只是"最后一个 body 节点的 outputs + 一份 _loop 记账",本原语不做任何投影
或裁剪。** 于是它可能带着一些循环内部的中间字段(典型如最后那一关的判定与评审
意见)按通道①流进循环后面的节点。这是刻意不管的:Loop 对外的正式接口是"从
continue_when 这条状态路径读、往 _loop.<name>.last 这条状态路径写",都在 State 上;
至于要不要把它的 outputs 当作后续节点的 inputs 来用,是场景方在自己的 Workflow
定义里决定的事,而每个节点真正需要什么本来就该由它自己的 reads 声明。原语不替场景
猜"哪些字段该留、哪些该扔"——那是业务语义,不是控制流形状(见 §6.5 的判断标准)。

与 Breaker(见 engine/primitives/breaker.py)的分工:continue_when 是"是非器",
只回答"这一轮算不算过";Breaker 是放进 body 里的普通 Node,回答的是一个完全独立
的问题——"不管这一轮过没过,现在就提前结束整个 Loop"。两者互不知晓对方存在:
Breaker 触发时(抛出 LoopBreak)不会去看 continue_when,直接把当前 outputs 当作
"通过"收尾。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from engine.stage import Node, StatePath
from engine.context import CheckpointRequest, RunContext
from engine.primitives.breaker import LoopBreak


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
    """迭代:对同一份输入反复执行 body,直到 continue_when 不再要求重来。

    Attributes:
        name:           循环名称(用于日志/断点定位,以及拼出游标路径)。
        body:           一轮要依次执行的节点(Sequence 的规则:上一个 outputs 流入
                        下一个 inputs)。每个节点跑完都会被问一次 continue_when。
        continue_when:  是非器——一条状态路径;每个节点跑完后取它的真假,真则本轮
                        到此为止、从 body[0] 重开一轮。通常指向游标里的判定字段,
                        如 "_loop.outline_loop.last.needs_revision"。
        max_iterations: 最多跑几轮,防止死循环。
        on_exceed:      跑满 max_iterations 仍在要求重来时的策略。
    """

    name: str
    body: list[Node] = field(default_factory=list)
    continue_when: StatePath = ""
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
            restart = False
            for node in self.body:
                try:
                    current = node.run(ctx, current)
                except LoopBreak as brk:
                    # Breaker 判定优先于是非器:不再检查 continue_when,直接当作
                    # "本轮通过、循环立即结束"收尾(与 hooks 的 passed=True 语义一致)。
                    if ctx.hooks and ctx.hooks.after_loop_iteration:
                        ctx.hooks.after_loop_iteration(self.name, i, True)
                    return self._finish(ctx, brk.outputs, iterations=i + 1, exhausted=False)
                self._publish(ctx, current)
                if bool(ctx.state.get(self.continue_when)):
                    restart = True
                    break  # 短路:本轮 body 剩下的节点不再执行。

            if ctx.hooks and ctx.hooks.after_loop_iteration:
                ctx.hooks.after_loop_iteration(self.name, i, not restart)

            if not restart:
                # body 完整跑完且没人要求重来 = 通过。
                return self._finish(ctx, current, iterations=i + 1, exhausted=False)

        # 跑满 max_iterations 仍在要求重来 -> 按 on_exceed 处理。
        if self.on_exceed == OnExceed.ACCEPT_LAST:
            return self._finish(
                ctx, current, iterations=self.max_iterations, exhausted=True
            )
        if self.on_exceed == OnExceed.ESCALATE_TO_CHECKPOINT:
            if ctx.checkpoint_handler is None:
                raise RuntimeError("Loop 超限,但 RunContext 未配置 checkpoint_handler")
            # 升级为人工裁决:current 是最后一轮最后执行的那个节点的产出(短路时
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
        字段会残留下来,是非器在下一轮的 body[0] 之后就读到陈旧的真值,循环永远
        跑不完。
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
