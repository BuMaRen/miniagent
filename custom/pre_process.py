import re

# 乾、坎、艮、震、巽、离、坤、兑
# 十二生肖顺序（公历4年为鼠年，按 (year - 4) % 12 求当年生肖）
_zodiac_order = ["鼠", "牛", "虎", "兔", "龙", "蛇", "马", "羊", "猴", "鸡", "狗", "猪"]

_pre_set = {
    "鼠": "乾",
    "牛": "坎",
    "虎": "艮",
    "兔": "震",
    "龙": "巽",
    "蛇": "离",
    "马": "坤",
    "羊": "兑",
    "猴": "休",
    "鸡": "生",
    "狗": "伤",
    "猪": "杜",
    "单": "阳",
    "双": "阴",
    "香": "惊",
    "门": "开",
    "小": "景",
    "大": "死",
    "港": "惊",
    "澳": "开",
    "单数": "阳",
    "双数": "阴",
    "香港": "惊",
    "澳门": "开",
    "小数": "景",
    "大数": "死",
}

_plan_rule = """
## 方案规则
1. “惊”和“开”是方案归属，不同归属的方案和数据分开计算，答复的时候也要分开
2. 方案默认归属“开”
3. “阳”代表奇数，“阳”修饰其他方案的时候会代表这些方案中所有奇数的集合
4. “阴”代表偶数，“阴”修饰其他方案的时候会代表这些方案中所有偶数的集合
5. “死”表示编号大于等于25的集合，“死”修饰其他方案的时候会代表这些方案中所有大于等于25的集合
6. “景”表示编号小于25的集合，“景”修饰其他方案的时候会代表这些方案中所有小于25的集合
7. “尾”表示后缀（余10）：其前面紧邻的一个或多个数字各自代表一个个位数（可以连写，如“786尾”，也可以用“.”等符号分隔，如“7.8.6尾”、“7/8/6/尾”、“7/8/6尾”），“尾”代表1~49中个位数等于这些数字的所有编号集合，例如“786尾”代表的编号集合为：7、8、6、17、18、16、27、28、26、37、38、36、47、48、46
8. “头”表示前缀（除10）：其前面紧邻的一个数字代表十位数，“头”代表1~49中除以10（向下取整）等于该数字的所有编号集合，例如“3头”代表的编号集合为：30、31、32、33、34、35、36、37、38、39
"""


def sensitive_transfer(user_input: str) -> str:
    """
    将 user_input 中出现的 _pre_set 键替换为对应的值。

    按键长度从长到短依次替换，避免像“单数”被“单”提前命中导致
    替换成“景数”而不是“景”这种子串误替换问题。

    Args:
        user_input: 原始用户输入文本。

    Returns:
        替换后的文本。
    """
    result = user_input
    for key in sorted(_pre_set, key=len, reverse=True):
        result = result.replace(key, _pre_set[key])
    return result


_DELIMITER_TRANSLATION = str.maketrans(
    {".": "/", "-": "/", "=": "/", "@": "/", "+": "/", "免": "兔"}
)


def normalize_delimiters(user_input: str) -> str:
    """
    将 user_input 中的 “.”、“-”、“=” 统一替换为 “/”。

    这三个符号在输入里分别被用作物品列表分隔符（如“8.20.44各5”）、
    <物品>-<数量> 记法（如“37-40”）、物品列表分隔符（如“27=16=29各30块”），
    和 “/” 已有的两种用法（物品列表分隔符 / 语义等同 “#” 的 <物品>/<数量> 记法）
    完全重合，统一成 “/” 后可以少维护三套等价的分隔符规则。

    Args:
        user_input: 原始用户输入文本。

    Returns:
        替换后的文本。
    """
    return user_input.translate(_DELIMITER_TRANSLATION)


def _zodiac_transfer(zodiac: str) -> str:
    """
    根据当前时间对应的生肖年份，计算指定生肖在1~49号码中的号码集合。

    规则：当前年份生肖对应1、13、25、37、49；再往前每退一个生肖，
    起始号码减1，依次循环（如去年生肖对应2、14、26、38，前年对应3、15、27、39……）。

    Args:
        zodiac: 生肖名称，如“鼠”“牛”等。

    Returns:
        形如 plans 中 "乾：1、13、25、37、49" 的字符串。
    """
    import datetime

    if zodiac not in _zodiac_order:
        raise ValueError(f"未知生肖: {zodiac}")

    current_index = (datetime.date.today().year - 4) % 12
    target_index = _zodiac_order.index(zodiac)
    offset = (current_index - target_index) % 12

    numbers = list(range(offset + 1, 50, 12))
    numbers_str = "、".join(str(n) for n in numbers)

    gua_name = _pre_set.get(zodiac, zodiac)
    return f"{gua_name}：{numbers_str}"


def _build_plans() -> str:
    lines = [
        f"{i}. {_zodiac_transfer(zodiac)}"
        for i, zodiac in enumerate(_zodiac_order, start=1)
    ]

    xiao_shu = "、".join(str(n) for n in range(1, 25))
    da_shu = "、".join(str(n) for n in range(25, 50))
    lines.append(f"{len(lines) + 1}. 景：{xiao_shu}")
    lines.append(f"{len(lines) + 1}. 死：{da_shu}")

    return "## 预设方案\n" + "\n".join(lines)


def split_input(user_input: str) -> list[str]:
    return [line for line in user_input.strip().splitlines() if line.strip()]


_MERGE_GROUP_SIZE = 5
_MERGE_SEPARATOR = "\n"
_EMPTY_PARENS_PATTERN = re.compile(r"[（(]\s*[）)]")


def pre_merge_input(lines: list[str]) -> list[str]:
    """
    将同一方案归属（惊/开）下的元素按每 5 行拼接为一个元素，以减少后续逐条
    调用模型的次数。

    归属判定：元素中包含“惊”记为“惊”，否则默认归为“开”（与 _plan_rule 规则2
    “方案默认归属‘开’”一致），逐行独立判断、不跨行继承。

    每个原始元素自身可能已经带有“惊”/“开”归属标识字符（sensitive_transfer 转换
    自 港/香/澳/门），如果直接拼接会导致同一组内重复出现多个归属标识、干扰模型
    解析。因此这里先把每行自带的归属标识字符去掉——这一步经常会在原文本中留下
    空括号（如“港(小)”被替换成“惊(小)”，标识去除后变成“惊()”），一并清理掉；
    再按判定出的归属分桶。

    每 5 行为一组，组内原始内容以换行拼接，组首统一加上一行“本次输入的内容
    全部归属于“惊/开”：”作为归属说明，保证每组只有一个、且位置固定在最前面。
    不同归属的元素不会被拼接到同一组中。

    Args:
        lines: split_input 拆分后的原始元素列表（通常先经过 sensitive_transfer）。

    Returns:
        合并后的元素列表；每个元素首行为归属说明，其后每行为一条原始内容。
    """

    def category_of(line: str) -> str:
        return "惊" if "惊" in line else "开"

    def strip_marker(line: str) -> str:
        stripped = line.replace("惊", "").replace("开", "")
        stripped = _EMPTY_PARENS_PATTERN.sub("", stripped)
        return stripped.strip()

    buckets: dict[str, list[str]] = {"惊": [], "开": []}
    for line in lines:
        buckets[category_of(line)].append(strip_marker(line))

    merged: list[str] = []
    for category in ("惊", "开"):
        items = buckets[category]
        for i in range(0, len(items), _MERGE_GROUP_SIZE):
            chunk = items[i : i + _MERGE_GROUP_SIZE]
            header = f"本次输入的内容全部归属于“{category}”："
            merged.append(header + _MERGE_SEPARATOR + _MERGE_SEPARATOR.join(chunk))

    return merged


_plans = _build_plans()

safety_plan_prompt = f"# 方案详情\n{_plans}\n{_plan_rule}"

# print(safety_plan_prompt)
