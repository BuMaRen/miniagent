
from typing import Any
from engine.context import RunContext
from engine.primitives.breaker import Breaker


def build_review_breaker(quota: int) -> Breaker:
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