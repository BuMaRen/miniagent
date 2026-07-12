import threading

from tools.schema import schema_from_func

_record = {}
_record_lock = threading.Lock()  # 并发处理同一 uuid 的多行输入时，保护累加操作的原子性

# 方案归属，与 pre_process.py 中 plan_rule 的定义保持一致
_CATEGORIES = ("惊", "开")


def record(uuid: str, parsed_data: dict[int, int], category: str = "开") -> str:
    """
    记录解析后的物品编号与数量，按方案归属（category）与 uuid 分别累加数量。

    Args:
        uuid: 用户的唯一标识符。
        parsed_data: 解析后的数据，键为物品编号，值为对应数量。
        category: 方案归属，"惊" 或 "开"，未指定时默认为 "开"（与 _plan_rule 的
            "方案默认归属开" 保持一致）。

    Returns:
        记录结果，成功返回 "处理成功"，失败返回 "处理失败"。
    """
    # 粉色字体打印当前处理的内容，便于定位失败是哪一行输入引发的
    print(f"\033[95m记录内容：uuid={uuid}, category={category}, parsed_data={parsed_data}\033[0m")
    try:
        with _record_lock:
            bucket = _record.setdefault(uuid, {}).setdefault(category, {})
            for item, quantity in parsed_data.items():
                bucket[item] = bucket.get(item, 0) + quantity
        return "处理成功"
    except Exception:
        return "处理失败"


def summary_record(uuid: str) -> str:
    """
    汇总某个 uuid 下已记录的物品数量，按方案归属（惊/开）分开输出。

    Args:
        uuid: 用户的唯一标识符。

    Returns:
        每个方案归属占一行，格式为 "归属：@@物品编号:数量 物品编号:数量 ...@@"。
    """
    categories = _record.get(uuid, {})
    lines = []
    for category in _CATEGORIES:
        items = categories.get(category, {})
        sorted_items = sorted(items.items(), key=lambda pair: int(pair[0]))
        body = " ".join(f"{item}:{quantity}" for item, quantity in sorted_items)
        lines.append(f"{category}：@@{body}@@")
    return "\n".join(lines)


record_tools = [
    (record, schema_from_func(record)),
]

