from tools.schema import schema_from_func

records = {}


def parse(plans: list[str]) -> dict[str, list[int]]:
    """
    解析套餐计划，返回套餐编号和对应的物品编号。

    Args:
        plans: 套餐计划列表，每个元素是一个字符串，表示一个套餐。

    Returns:
        一个字典，键为套餐编号，值为对应的物品编号。
    """
    result = dict()

    plan_map = {
        "小数": [i for i in range(1, 25)],
        "小数单": [i for i in range(1, 25) if i % 2 == 1],
        "小数双": [i for i in range(1, 25) if i % 2 == 0],
        "大数": [i for i in range(25, 50)],
        "大数单": [i for i in range(25, 50) if i % 2 == 1],
        "大数双": [i for i in range(25, 50) if i % 2 == 0],
        "鼠": [7, 19, 31, 43],
        "牛": [6, 18, 30, 42],
        "虎": [5, 17, 29, 41],
        "兔": [4, 16, 28, 40],
        "龙": [3, 15, 27, 39],
        "蛇": [2, 14, 26, 38],
        "马": [1, 13, 25, 37, 49],
        "羊": [12, 24, 36, 48],
        "猴": [11, 23, 35, 47],
        "鸡": [10, 22, 34, 46],
        "狗": [9, 21, 33, 45],
        "猪": [8, 20, 32, 44],
    }

    for plan in plans:
        if "尾" in plan:
            result[plan] = _get_numbers(plan)
            continue
        if plan in plan_map:
            result[plan] = plan_map[plan]
            continue
    return result


def _get_numbers(num_tail: str) -> list[int]:
    """
    根据尾数获取对应的物品编号列表。

    Args:
        num_tail: 尾数字符串，表示物品编号的尾数。

    Returns:
        对应的物品编号列表。
    """
    import re

    # 获取尾数中的数字部分
    tail_numbers = re.findall(r"\d", num_tail)
    numbers = []
    for tail in tail_numbers:
        tail = int(tail)
        for i in range(1, 50):
            if i % 10 == tail:
                numbers.append(i)
    return numbers


def id_generate() -> str:
    """
    生成一个唯一的订单编号。

    Returns:
        一个唯一的订单编号字符串。
    """
    import uuid

    return str(uuid.uuid4())


def record(uuid: str, source_line: str, parsed_result: str):
    """
    记录每行的解析结果。

    Args:
        source_line: 原始输入行。
        parsed_result: 解析结果，格式为“@@物品编号:数量 物品编号:数量 ...@@”。
    """
    print(f"Recording: {uuid} {source_line} -> {parsed_result}")

    if uuid not in records:
        records[uuid] = dict()
    parsed_result = parsed_result.strip().strip("@@")
    for pair in parsed_result.split(" "):
        item, count = pair.split(":")
        item = int(item)
        if item not in records[uuid]:
            records[uuid][item] = 0
        records[uuid][item] += int(count)


def summary_record(uuid: str) -> str:
    """
    生成最终的汇总结果。

    Args:
        uuid: 订单编号。

    Returns:
        汇总结果字符串，格式为“@@物品编号:数量 物品编号:数量 ...@@”。
    """
    if uuid not in records:
        return "@@ @@"

    summary = records[uuid]
    sorted_items = sorted(summary.items(), key=lambda x: int(x[0]))
    result = " ".join(f"{item}:{count}" for item, count in sorted_items)
    result = result.strip()
    return f"@@{result}@@"


liuhe_tools = [
    (parse, schema_from_func(parse)),
    (id_generate, schema_from_func(id_generate)),
    (record, schema_from_func(record)),
    (summary_record, schema_from_func(summary_record)),
]
