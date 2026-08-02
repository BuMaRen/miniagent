"""用户输入契约 —— 规定"用户要填哪些设定",并把 brief.yaml 校验成 State 里的
short_story.brief。

这是本场景的两份 prompt 中的**用户那一份**:用户在 brief.yaml 里描述"写什么",
本模块负责校验、补默认值、规整类型;流程侧"怎么写"的那一份在 prompts.py,
两边不共用一个字符串,也不互相拼接 —— 流程 prompt 只通过 State 读到这份 brief,
所以换题材永远不会改到流程,写坏 brief 也永远污染不了流程的写作准则。

字段清单在这里唯一定义(BRIEF_FIELDS),brief.yaml 的注释、README 的说明、
state_schema.BRIEF 都以它为准;多填一个没见过的键会直接报错而不是被静默忽略
——设定被无声吞掉是最难查的一类"模型没按我说的写"。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# 篇幅的硬边界。用户可以在区间内自定,但短篇网文的体裁本身决定了它不该被填成
# 3000 或 50000 —— 那是另外两种东西,对应的节奏与爽点密度都不一样。
MIN_TARGET_WORDS = 6000
MAX_TARGET_WORDS = 15000
DEFAULT_TARGET_WORD_COUNT = [8000, 10000]


@dataclass(frozen=True)
class BriefField:
    """一个用户设定项。

    Attributes:
        name:     字段名(brief.yaml 里的键)。
        required: 是否必填。
        default:  缺省值;required 为 True 时无意义。
        kind:     "text" | "list" | "range" | "int",决定怎么规整取值。
        note:     给用户看的说明(README 与报错信息都用它)。
    """

    name: str
    required: bool
    default: Any
    kind: str
    note: str


BRIEF_FIELDS: tuple[BriefField, ...] = (
    BriefField("premise", True, None, "text", "一句到一段话讲清这个故事:谁、遇到什么、要干什么"),
    BriefField("setting", False, "", "text", "时代/地点/世界规则等背景设定,留空则由模型自行设定"),
    BriefField("protagonist", False, "", "text", "主角设定:身份、初始处境、底牌或优势"),
    BriefField("antagonist", False, "", "text", "对手或压力来源:可以是具体的人,也可以是处境/制度"),
    BriefField("hook_types", False, [], "list", "想要的爽点类型,如 打脸、逆袭、扮猪吃虎、身份反转、复仇"),
    BriefField("ending", False, "", "text", "期望的结局走向,留空则由模型决定"),
    BriefField("genre", False, "", "text", "题材标签,如 都市、玄幻、悬疑、职场"),
    BriefField("pov", False, "第三人称限知视角", "text", "叙述人称与视角,全篇不得漂移"),
    BriefField("tone", False, "", "text", "语气基调,如 轻松诙谐、冷硬克制、热血"),
    BriefField("taboos", False, "", "text", "不希望出现的内容(题材禁忌、不想要的桥段)"),
    BriefField("extra", False, "", "text", "其他要求:必须出现的桥段、指定的名字、结尾方式等"),
    BriefField(
        "target_word_count", False, DEFAULT_TARGET_WORD_COUNT, "range",
        f"目标总字数区间 [下限, 上限],需落在 [{MIN_TARGET_WORDS}, {MAX_TARGET_WORDS}] 内",
    ),
    BriefField("section_count", False, 4, "int", "希望分成几节;留空默认 4 节,也可填 0 表示由大纲阶段自己决定(4-10 节)"),
)

_FIELDS_BY_NAME = {f.name: f for f in BRIEF_FIELDS}


def load_brief(path: Path | str) -> dict[str, Any]:
    """读取 brief.yaml 并校验成一份可写进 short_story.brief 的 dict。"""
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: brief 必须是一个 YAML 映射(键: 值),得到 {type(raw).__name__}")
    return parse_brief(raw)


def parse_brief(raw: dict[str, Any]) -> dict[str, Any]:
    """校验用户设定、补默认值、规整类型,返回完整的 brief。

    Raises:
        ValueError: 必填项缺失、出现未知字段、或字数区间不合法。
    """
    unknown = [k for k in raw if k not in _FIELDS_BY_NAME]
    if unknown:
        raise ValueError(
            f"brief 里出现了未知设定项 {unknown};可填的设定项只有:"
            + "、".join(f.name for f in BRIEF_FIELDS)
        )

    brief: dict[str, Any] = {}
    for field in BRIEF_FIELDS:
        value = raw.get(field.name)
        if value is None or (isinstance(value, str) and not value.strip()):
            if field.required:
                raise ValueError(f"brief 缺少必填设定项 {field.name!r}:{field.note}")
            value = field.default
        brief[field.name] = _coerce(field, value)

    low, high = brief["target_word_count"]
    if low > high:
        raise ValueError(f"target_word_count 的下限 {low} 大于上限 {high}")
    if low < MIN_TARGET_WORDS or high > MAX_TARGET_WORDS:
        raise ValueError(
            f"target_word_count {[low, high]} 超出本场景支持的范围 "
            f"[{MIN_TARGET_WORDS}, {MAX_TARGET_WORDS}] —— 短篇网文的节奏是按这个量级设计的,"
            "要写更长请改用 scenarios/novel。"
        )
    if brief["section_count"] and not 4 <= brief["section_count"] <= 10:
        raise ValueError(f"section_count 只能填 0(自动)或 4-10,得到 {brief['section_count']}")
    return brief


def _coerce(field: BriefField, value: Any) -> Any:
    """按字段类型规整取值,顺手把常见的手写偏差(如把列表写成一行顿号分隔)接住。"""
    if field.kind == "text":
        return str(value).strip()
    if field.kind == "list":
        if isinstance(value, str):
            return [item.strip() for item in value.replace(",", "、").split("、") if item.strip()]
        return [str(item).strip() for item in value]
    if field.kind == "int":
        return int(value)
    if field.kind == "range":
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            raise ValueError(f"{field.name} 须写成 [下限, 上限] 两个整数,得到 {value!r}")
        return [int(value[0]), int(value[1])]
    raise ValueError(f"未知的字段类型 {field.kind!r}(BRIEF_FIELDS 定义有误)")


def describe_fields() -> str:
    """把字段清单渲染成给人看的说明(供 run.py 的 --show-fields 与报错提示复用)。"""
    lines = ["本场景可填的设定项(brief.yaml):"]
    for field in BRIEF_FIELDS:
        mark = "必填" if field.required else f"选填,默认 {field.default!r}"
        lines.append(f"  {field.name:<18}({mark}) {field.note}")
    return "\n".join(lines)
