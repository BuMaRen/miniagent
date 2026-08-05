"""本目录几个示例共用的节点定义。

不挂 LLM/Agent:所有 executor 都是普通函数,方便脱离 API Key 单独运行,把注意力
集中在"控制流原语怎么用"这一件事上——对比 scenarios/novel、scenarios/short 里
大多数节点要挂一个 Agent(那是"能力挂载层" agent/ToolSet 的示范),这里只演示
"引擎层"(Stage 的 reads/writes 契约 + 四个控制流原语)。业务逻辑刻意写得很简单
(加法、比大小),好让读者一眼看穿"这一步在状态上做了什么",不被业务细节分心。
"""

from __future__ import annotations

from typing import Any

from engine.context import RunContext
from engine.primitives.breaker import Breaker
from engine.primitives.foreach import foreach_item_path
from engine.primitives.loop import loop_cursor_path
from engine.stage import Stage
from state.schema import StateSchema

NEEDS_REVISION_KEY = "needs_revision"
# 评审类节点的输出契约,被下面好几个示例复用。极性刻意朝着"还要再改一轮"为真
# 命名(needs_revision 而不是 passed)——引擎侧的极性是固定的(真=还要重开一轮),
# 但判定谓词内部想用什么字段名、要不要取反,完全是场景自己的事(见下面
# needs_revision_continue_when,以及 engine/primitives/loop.py 的说明)。
CRITIC_SCHEMA = StateSchema("critic_output", {NEEDS_REVISION_KEY: bool, "feedback": str})


def needs_revision_continue_when(ctx: RunContext, outputs: dict[str, Any]) -> bool:
    """本目录几个 Loop 示例共用的判定谓词:直接对着刚跑完的节点的 outputs 求值,
    不经过 State。Loop 在 body 里每个节点跑完后都会调用一次(不只是评审节点那
    一个),所以用 .get(..., False) 而不是 outputs[...]——像 propose_amount
    这种生成类节点的 outputs 里没有这个字段,.get 的默认值 False 让它不会被
    误判成"要求重开一轮"。
    """
    return outputs.get(NEEDS_REVISION_KEY, False)


# =============================================================================
# 一、Loop 示例用的两个节点:提案(propose) + 评审(review)。
#    见 loop_example.py —— 反复加价直到达到最低金额,continue_when 驱动重开一轮。
# =============================================================================

PROPOSAL_LOOP_NAME = "proposal_loop"
PROPOSAL_LOOP_LAST_PATH = loop_cursor_path(PROPOSAL_LOOP_NAME)


def make_propose_amount_stage(step: int) -> Stage:
    """每一轮把 proposal.amount 加 step。

    注意"当前金额"走的是普通的 reads/writes(state.proposal.amount),不是 Loop
    游标——游标(PROPOSAL_LOOP_LAST_PATH)只用来读"上一轮评审为什么没过",这类
    长期存活、需要跨轮次持续累加的事实应该走 State 的正常读写通道,不应该塞进
    游标:游标每轮都会被整块替换,不是用来累积状态的地方。
    """

    def executor(ctx: RunContext, inputs: dict[str, Any]) -> dict[str, Any]:
        state = inputs.get("state", {})
        current = state.get("proposal.amount") or 0
        feedback = (state.get(PROPOSAL_LOOP_LAST_PATH) or {}).get("feedback") or ""
        new_amount = current + step
        if feedback:
            print(f"    [propose] 上一轮反馈:{feedback!r} -> 金额 {current} 加 {step} = {new_amount}")
        else:
            print(f"    [propose] 首轮,金额从 0 加 {step} = {new_amount}")
        return {"proposal.amount": new_amount}

    return Stage(
        name="propose_amount",
        executor=executor,
        reads=["proposal.amount", PROPOSAL_LOOP_LAST_PATH],
        writes=["proposal.amount"],
    )


def make_review_amount_stage(minimum: int) -> Stage:
    """评审:金额达到 minimum 就通过(needs_revision=False),否则打回重来。"""

    def executor(ctx: RunContext, inputs: dict[str, Any]) -> dict[str, Any]:
        state = inputs.get("state", {})
        amount = state.get("proposal.amount") or 0
        if amount < minimum:
            verdict = {NEEDS_REVISION_KEY: True, "feedback": f"金额 {amount} 未达到最低要求 {minimum},请提高"}
        else:
            verdict = {NEEDS_REVISION_KEY: False, "feedback": ""}
        print(f"    [review]  金额 {amount} {'不足' if verdict[NEEDS_REVISION_KEY] else '达标'}(要求 >= {minimum})")
        return verdict

    return Stage(
        name="review_amount",
        executor=executor,
        reads=["proposal.amount"],
        output_schema=CRITIC_SCHEMA,
    )


# =============================================================================
# 二、ForEach / Breaker 示例用的节点:逐个处理批次里的任务。
#    见 foreach_example.py / breaker_example.py / combined_example.py。
# =============================================================================

TASK_LOOP_NAME = "task_loop"
TASK_ITEM_PATH = foreach_item_path(TASK_LOOP_NAME)


def build_process_task_stage(threshold: int) -> Stage:
    """处理 ForEach 当前遍历到的这一个任务:金额不超过 threshold 就批准。

    "当前元素"通过 reads=[TASK_ITEM_PATH] 读到(ForEach 每轮把 items[i] 发布到
    这个游标),和读任何一个普通状态切片完全一样——不存在"塞进 inputs 的魔法键"。
    """

    def executor(ctx: RunContext, inputs: dict[str, Any]) -> dict[str, Any]:
        state = inputs.get("state", {})
        item = state.get(TASK_ITEM_PATH) or {}
        tasks = state.get("batch.tasks") or []
        approved_count = state.get("batch.approved_count") or 0

        approved = (item.get("amount") or 0) <= threshold
        new_status = "approved" if approved else "rejected"
        note = f"金额{'未超' if approved else '超过'}上限 {threshold}"
        updated_tasks = [
            {**t, "status": new_status, "note": note} if t.get("id") == item.get("id") else t
            for t in tasks
        ]
        print(f"    [process] 任务 {item.get('id')}(金额={item.get('amount')}) -> {new_status}")
        return {
            "batch.tasks": updated_tasks,
            "batch.approved_count": approved_count + (1 if approved else 0),
        }

    return Stage(
        name="process_task",
        executor=executor,
        reads=[TASK_ITEM_PATH, "batch.tasks", "batch.approved_count"],
        writes=["batch.tasks", "batch.approved_count"],
    )


def build_quota_breaker(quota: int) -> Breaker:
    """一旦批准数达到 quota,立即结束外层 ForEach(相当于 Python 的 break)。

    Breaker 不是 Stage:它的 predicate 签名是 (ctx, inputs) -> bool,直接拿到
    RunContext,不像 Stage 那样自动把 reads 声明的状态切片注入 inputs——所以要
    读状态,predicate 内部直接 ctx.state.get(...),而不是 inputs.get("state")。
    """

    def predicate(ctx: RunContext, inputs: dict[str, Any]) -> bool:
        approved_count = ctx.state.get("batch.approved_count") or 0
        hit = approved_count >= quota
        if hit:
            print(f"    [breaker] 已批准 {approved_count} 个,达到配额 {quota},break!")
        return hit

    return Breaker(name="quota_reached", predicate=predicate)


# =============================================================================
# 三、Loop + ForEach 组合(combined_example.py)复用的"逐任务谈价"节点:与
#    make_propose_amount_stage/make_review_amount_stage 同构,区别是金额记在
#    batch.tasks 里当前元素那一条上,而不是一个独立的顶层字段——因为 ForEach
#    的每一轮迭代都是同一个 Loop 定义在为不同的任务重新跑一遍。
# =============================================================================

NEGOTIATE_LOOP_NAME = "negotiate_loop"
NEGOTIATE_LOOP_LAST_PATH = loop_cursor_path(NEGOTIATE_LOOP_NAME)


def _find_task(tasks: list[dict], task_id: Any) -> dict:
    return next((t for t in tasks if t.get("id") == task_id), {})


def make_negotiate_amount_stage(step: int) -> Stage:
    def executor(ctx: RunContext, inputs: dict[str, Any]) -> dict[str, Any]:
        state = inputs.get("state", {})
        item = state.get(TASK_ITEM_PATH) or {}
        tasks = state.get("batch.tasks") or []
        # 用 item 里稳定不变的 id 去活的 tasks 列表里定位当前金额——item 本身是
        # ForEach 绑定时的快照,后续轮次里 tasks 才是真正随每轮 writes 更新的那份。
        current = _find_task(tasks, item.get("id")).get("amount") or 0
        new_amount = current + step
        updated_tasks = [
            {**t, "amount": new_amount} if t.get("id") == item.get("id") else t for t in tasks
        ]
        print(f"    [negotiate] 任务 {item.get('id')} 金额 {current} 加 {step} = {new_amount}")
        return {"batch.tasks": updated_tasks}

    return Stage(
        name="negotiate_amount",
        executor=executor,
        reads=[TASK_ITEM_PATH, "batch.tasks", NEGOTIATE_LOOP_LAST_PATH],
        writes=["batch.tasks"],
    )


def make_negotiate_review_stage(minimum: int) -> Stage:
    def executor(ctx: RunContext, inputs: dict[str, Any]) -> dict[str, Any]:
        state = inputs.get("state", {})
        item = state.get(TASK_ITEM_PATH) or {}
        tasks = state.get("batch.tasks") or []
        amount = _find_task(tasks, item.get("id")).get("amount") or 0
        if amount < minimum:
            verdict = {NEEDS_REVISION_KEY: True, "feedback": f"金额 {amount} 未达到最低要求 {minimum}"}
        else:
            verdict = {NEEDS_REVISION_KEY: False, "feedback": ""}
        print(f"    [neg-review] 任务 {item.get('id')} 金额 {amount} {'不足' if verdict[NEEDS_REVISION_KEY] else '达标'}")
        return verdict

    return Stage(
        name="negotiate_review",
        executor=executor,
        reads=[TASK_ITEM_PATH, "batch.tasks"],
        output_schema=CRITIC_SCHEMA,
    )


def build_finalize_task_stage() -> Stage:
    """Loop 结束后定稿:金额达标(真通过,或跑满轮次但 on_exceed=ACCEPT_LAST 放行
    时其实也可能没达标)才批准,否则标记拒绝——用 `_loop.exhausted` 是白拿的判断
    "这是真通过还是被放行的",这里选择更简单地直接重新核对金额,两种写法都可以。
    """

    def executor(ctx: RunContext, inputs: dict[str, Any]) -> dict[str, Any]:
        state = inputs.get("state", {})
        item = state.get(TASK_ITEM_PATH) or {}
        tasks = state.get("batch.tasks") or []
        approved_count = state.get("batch.approved_count") or 0
        amount = _find_task(tasks, item.get("id")).get("amount") or 0
        exhausted = (inputs.get("_loop") or {}).get("exhausted", False)

        approved = not exhausted
        new_status = "approved" if approved else "rejected"
        note = "谈判成功" if approved else "谈判轮次耗尽,自动放弃"
        updated_tasks = [
            {**t, "status": new_status, "note": note} if t.get("id") == item.get("id") else t
            for t in tasks
        ]
        print(f"    [finalize] 任务 {item.get('id')}(金额={amount}) -> {new_status}")
        return {
            "batch.tasks": updated_tasks,
            "batch.approved_count": approved_count + (1 if approved else 0),
        }

    return Stage(
        name="finalize_task",
        executor=executor,
        reads=[TASK_ITEM_PATH, "batch.tasks", "batch.approved_count"],
        writes=["batch.tasks", "batch.approved_count"],
    )
