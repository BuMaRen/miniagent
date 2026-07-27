"""StateSchema —— 场景方提供的状态字段定义与校验。

引擎自身不含任何字段语义;场景方通过一份 StateSchema 声明"这份共享状态长什么样"
(小说场景的实例见 docs/story-bible-schema.md)。Schema 用于:初始化空状态、
校验 patch/append 写入是否合法、以及 Stage 的 input/output 契约校验。

definition 的表示法(自定义"类型树",零三方依赖,与本仓库其余部分一致):
    每个节点是下列之一 ——
      · 标量类型 str / int / float / bool  —— 值须是该类型(bool 不当作 int)。
      · dict{字段名: 子描述符}              —— 对象;默认拒绝未声明的键(抓拼写错)。
      · [子描述符]  (单元素列表)           —— 同构列表,每个元素匹配该子描述符。
      · Optional(子描述符)                 —— 允许 None,否则匹配子描述符(如 int|null)。
      · OneOf(v1, v2, ...)                  —— 枚举字面量(如 role 的三选一)。
      · ANY                                 —— 不施加任何约束。
    definition 为 None 时,整份 schema 视作完全宽松(不校验)。

小说 Story Bible 的 characters 片段大致可写成:
    OneOf, Optional, ANY 组合出——
    {"characters": [{
        "id": str, "name": str,
        "role": OneOf("protagonist", "antagonist", "supporting"),
        "status_log": [{"after_chapter": int, "state": str}],
    }]}

刻意保留的取舍(便于后续按需加强,不在本次范围):
    · 对象字段一律"可缺省但类型受校验"——为的是配合状态的增量写入(patch 只带
      本次变更的字段);因此 validate 不强制"必填字段存在"。若 Stage 的 input/
      output 需要必填语义,可日后引入 Required 包装。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class SchemaError(ValueError):
    """校验失败;消息里带出错路径,便于定位。属 ValueError 便于上层统一捕获。"""


class _AnyType:
    """ANY 的类型。用独立哨兵而非 None,以区分"不约束"与"没声明"。"""

    def __repr__(self) -> str:  # 让错误信息好读
        return "ANY"


ANY = _AnyType()


class Optional:
    """允许 None,否则按 inner 校验(对应 story bible 里的 `int | null`)。"""

    def __init__(self, inner: Any) -> None:
        self.inner = inner

    def __repr__(self) -> str:
        return f"Optional({self.inner!r})"


class OneOf:
    """枚举:值必须是列出的字面量之一(对应 `protagonist|antagonist|supporting`)。"""

    def __init__(self, *choices: Any) -> None:
        self.choices = choices

    def __repr__(self) -> str:
        return f"OneOf{self.choices!r}"


def _unwrap(desc: Any) -> Any:
    """剥掉 Optional 外壳,取到真正的结构描述符(用于路径下钻)。"""
    while isinstance(desc, Optional):
        desc = desc.inner
    return desc


def _is_index(seg: str) -> bool:
    """路径段是否是列表下标(如 "0"、"-1")。"""
    return seg.isdigit() or (seg[:1] == "-" and seg[1:].isdigit())


def _validate(desc: Any, value: Any, path: str) -> None:
    """按描述符 desc 递归校验 value;path 仅用于报错定位。"""
    where = path or "<root>"

    if desc is ANY or isinstance(desc, _AnyType) or desc is None:
        return

    if isinstance(desc, Optional):
        if value is None:
            return
        _validate(desc.inner, value, path)
        return

    if isinstance(desc, OneOf):
        if value not in desc.choices:
            raise SchemaError(f"{where}: 期望取值 ∈ {desc.choices!r},得到 {value!r}")
        return

    if isinstance(desc, type):  # 标量类型
        # bool 是 int 的子类:必须先于 int 判定,避免 True/False 混入 int 字段;
        # int 字段也要排除 bool;float 宽松地接纳 int(但同样排除 bool)。
        if desc is bool:
            ok = isinstance(value, bool)
        elif desc is int:
            ok = isinstance(value, int) and not isinstance(value, bool)
        elif desc is float:
            ok = isinstance(value, (int, float)) and not isinstance(value, bool)
        else:
            ok = isinstance(value, desc)
        if not ok:
            raise SchemaError(
                f"{where}: 期望 {desc.__name__},得到 {type(value).__name__}"
            )
        return

    if isinstance(desc, list):  # [子描述符]:同构列表
        elem = desc[0]
        if not isinstance(value, list):
            raise SchemaError(f"{where}: 期望 list,得到 {type(value).__name__}")
        for i, v in enumerate(value):
            _validate(elem, v, f"{path}[{i}]")
        return

    if isinstance(desc, dict):  # 对象
        if not isinstance(value, dict):
            raise SchemaError(f"{where}: 期望 object,得到 {type(value).__name__}")
        for k in value:
            if k not in desc:
                raise SchemaError(f"{where}: 未声明的字段 {k!r}")
        for k, sub in desc.items():
            if k in value:
                _validate(sub, value[k], f"{path}.{k}" if path else k)
        return

    raise SchemaError(f"{where}: 无法识别的 schema 描述符 {desc!r}")


_JSON_TYPE_MAP: dict[type, str] = {str: "string", int: "integer", float: "number", bool: "boolean"}


def _to_json_schema(desc: Any) -> dict[str, Any]:
    """把描述符递归转成 JSON Schema,供 LLM Provider 的结构化输出模式使用。

    刻意生成两家 Provider strict 模式都能接受的形状:对象一律
    additionalProperties=false 且所有字段进 required(可选性改用
    Optional -> nullable 表达,而不是从 required 里剔除)。
    """
    if desc is ANY or isinstance(desc, _AnyType) or desc is None:
        return {}
    if isinstance(desc, Optional):
        return {"anyOf": [_to_json_schema(desc.inner), {"type": "null"}]}
    if isinstance(desc, OneOf):
        return {"enum": list(desc.choices)}
    if isinstance(desc, type) and desc in _JSON_TYPE_MAP:
        return {"type": _JSON_TYPE_MAP[desc]}
    if isinstance(desc, list):
        return {"type": "array", "items": _to_json_schema(desc[0])}
    if isinstance(desc, dict):
        return {
            "type": "object",
            "properties": {k: _to_json_schema(v) for k, v in desc.items()},
            "required": list(desc.keys()),
            "additionalProperties": False,
        }
    raise SchemaError(f"无法识别的 schema 描述符 {desc!r}")


def _empty(desc: Any) -> Any:
    """按描述符生成一个"类型正确的零值",作为空初始状态的骨架。"""
    if isinstance(desc, Optional) or isinstance(desc, OneOf):
        return None  # 可空字段/枚举没有天然零值,留空由后续填
    if desc is ANY or isinstance(desc, _AnyType) or desc is None:
        return None
    if isinstance(desc, list):
        return []
    if isinstance(desc, dict):
        return {k: _empty(v) for k, v in desc.items()}
    if isinstance(desc, type):
        return {str: "", int: 0, float: 0.0, bool: False}.get(desc, None)
    return None


@dataclass
class StateSchema:
    """状态结构声明。

    Attributes:
        name:       schema 名称(如 "story_bible")。
        definition: 字段定义(见模块 docstring 的类型树表示法);None 表示不校验。
    """

    name: str
    definition: Any = field(default=None)

    def empty(self) -> dict[str, Any]:
        """构造一个符合 schema 的空初始状态(用于新一次运行的起点)。

        对象逐字段填零值、列表填 []、标量填对应零值、可空字段填 None。
        definition 为 None 时返回空 dict。
        """
        if self.definition is None:
            return {}
        result = _empty(self.definition)
        # 顶层约定为对象;若场景把 definition 写成了非对象,兜底成 {} 以符合返回类型。
        return result if isinstance(result, dict) else {}

    def to_json_schema(self) -> dict[str, Any]:
        """转成 JSON Schema,供 LLM Provider 的结构化输出模式(OpenAI response_format /
        Anthropic output_config)使用。definition 为 None 时返回空 schema(不作约束)。
        """
        if self.definition is None:
            return {}
        return _to_json_schema(self.definition)

    def validate(self, data: dict[str, Any]) -> None:
        """校验一份数据是否符合 schema;不符合抛出带清晰路径的 SchemaError。"""
        _validate(self.definition, data, "")

    def validate_path(self, path: str, value: Any) -> None:
        """校验对某个路径的写入是否合法(供 StateStore.patch/append 调用)。

        先顺着 definition 下钻到该 path 对应的子描述符,再校验 value。
        列表目标存在二义性:patch 传"整张列表",append 传"单个元素"——同一路径
        两种形态都应放行,故对 list 描述符先按整表校验,失败再按元素校验。
        """
        if self.definition is None:
            return
        desc = self._resolve(path)
        if isinstance(desc, list):
            try:
                _validate(desc, value, path)          # patch:整张列表
            except SchemaError:
                _validate(desc[0], value, path)        # append:单个元素
            return
        _validate(desc, value, path)

    def _resolve(self, path: str) -> Any:
        """顺着点分路径在 definition 里下钻,返回该路径对应的子描述符。"""
        desc: Any = self.definition
        walked: list[str] = []
        for seg in path.split("."):
            walked.append(seg)
            here = ".".join(walked)
            desc = _unwrap(desc)
            # ANY 之下的任何子路径都不再约束。
            if desc is ANY or isinstance(desc, _AnyType) or desc is None:
                return ANY
            if _is_index(seg):
                if not isinstance(desc, list):
                    raise SchemaError(f"{here}: 用下标索引了非 list 的字段")
                desc = desc[0]
            elif isinstance(desc, dict):
                if seg not in desc:
                    raise SchemaError(f"{here}: schema 未声明该路径段 {seg!r}")
                desc = desc[seg]
            else:
                raise SchemaError(f"{here}: 路径超出了 schema 结构(在标量/枚举处继续下钻)")
        return desc
