"""数据声明示例 —— state.schema.StateSchema 的类型树写法一览。

这份文件不是一个可运行的场景,是给本目录下几个原语示例共用的"数据长什么样"参考。
覆盖:标量类型、OneOf 枚举、ANY 不约束、嵌套对象、同构列表,以及 StateSchema
提供的四个能力(empty / validate / validate_path / to_json_schema /
to_prompt_example)。写一个新场景的第一步永远是先把"状态长什么样"想清楚,再拆
Stage——见 scenarios/development-guide.md §2/§4,这里只演示语法本身。

直接运行本文件(`python -m scenarios.examples.state_schema`)能看到每个能力的
实际输出,不需要任何依赖或 API Key。
"""

from __future__ import annotations

from state.schema import ANY, OneOf, StateSchema

# ---------------------------------------------------------------------------
# 标量类型:str / int / float / bool 直接写 Python 内置类型即可;bool 不会被
# 误当成 int(先判定 bool 再判定 int,见 state/schema.py 的 _validate)。
#
# 枚举:OneOf(v1, v2, ...) —— 取值必须是列出的字面量之一,取值范围在装配期就
# 写死,不是运行期才知道。
# ---------------------------------------------------------------------------

TASK_STATUS = OneOf("pending", "approved", "rejected", "skipped")

# 对象:dict{字段名: 子描述符}。默认拒绝未声明的键,能在装配期就抓到拼写错误
# (比如把 "amount" 误写成 "amonut"),但不强制"必填"——写入是增量式的
# (patch 只带本次变更的字段),所以校验的是"类型对不对",不是"填没填全"。
TASK = {
    "id": str,
    "amount": int,        # 申请金额;loop_example / combined_example 会反复修订它
    "status": TASK_STATUS,
    "note": str,           # 评审意见;没有专门的"可空"类型,空字符串代表"暂无"
}

# ---------------------------------------------------------------------------
# 三份 definition 各自服务不同的示例,刻意分开而不是揉成一份大 schema,方便你在
# 只看某一个示例文件时不必先理解其它示例引入的字段。
# ---------------------------------------------------------------------------

# loop_example.py:一份"提案金额"反复修订,不需要列表,也不需要 ForEach。
LOOP_DEMO_DEFINITION = {"proposal": {"amount": int}}
LOOP_DEMO_SCHEMA = StateSchema(name="loop_demo", definition=LOOP_DEMO_DEFINITION)

# foreach_example.py / breaker_example.py / combined_example.py 共用:一批待审批
# 任务,ForEach 逐个处理;approved_count 用来给 Breaker 的 predicate 判断
# "配额是否已满"——同构列表写法是 [子描述符](这里是 [TASK]),表示"元素都长
# TASK 这个样子"。
BATCH_DEFINITION = {
    "batch": {
        "tasks": [TASK],
        "approved_count": int,
        "note": ANY,   # ANY:不对这个子树施加任何约束,这里只是演示语法
    }
}
BATCH_SCHEMA = StateSchema(name="batch_demo", definition=BATCH_DEFINITION)


def loop_demo_empty_state() -> dict:
    """构造一份符合 LOOP_DEMO_SCHEMA 的空状态。"""
    return LOOP_DEMO_SCHEMA.empty()


def batch_empty_state() -> dict:
    """构造一份符合 BATCH_SCHEMA 的空状态。"""
    return BATCH_SCHEMA.empty()


def make_batch_state(tasks: list[dict]) -> dict:
    """便捷构造:塞进一批初始任务,供各示例复用。"""
    state = batch_empty_state()
    state["batch"]["tasks"] = tasks
    return state


if __name__ == "__main__":
    import json

    print("=== LOOP_DEMO_SCHEMA.empty() ===")
    print(json.dumps(loop_demo_empty_state(), ensure_ascii=False, indent=2))

    print("\n=== BATCH_SCHEMA.empty() ===")
    print(json.dumps(batch_empty_state(), ensure_ascii=False, indent=2))

    print("\n=== BATCH_SCHEMA.to_json_schema()(喂给 Provider 结构化输出模式的形状) ===")
    print(json.dumps(BATCH_SCHEMA.to_json_schema(), ensure_ascii=False, indent=2))

    print("\n=== BATCH_SCHEMA.to_prompt_example()(给提示词当占位符示例) ===")
    print(BATCH_SCHEMA.to_prompt_example())

    print("\n=== validate():拒绝未声明字段(抓拼写错误) ===")
    try:
        BATCH_SCHEMA.validate(
            {
                "batch": {
                    "tasks": [
                        {"id": "t1", "amount": 100, "status": "pending", "note": "", "typo": 1}
                    ],
                    "approved_count": 0,
                    "note": None,
                }
            }
        )
    except Exception as exc:  # SchemaError
        print(f"预期报错: {exc}")

    print("\n=== validate():枚举取值必须是 OneOf 列出的字面量之一 ===")
    try:
        BATCH_SCHEMA.validate(
            {"batch": {"tasks": [{"id": "t1", "amount": 1, "status": "not-a-status", "note": ""}], "approved_count": 0, "note": None}}
        )
    except Exception as exc:
        print(f"预期报错: {exc}")

    print("\n=== validate_path():校验单条状态路径的写入(Stage.writes 走的就是这条) ===")
    try:
        BATCH_SCHEMA.validate_path("batch.tasks.0.status", "not-a-valid-status")
    except Exception as exc:
        print(f"预期报错: {exc}")
    BATCH_SCHEMA.validate_path("batch.tasks.0.status", "approved")
    print("合法值 'approved' 校验通过(无输出即成功)。")
