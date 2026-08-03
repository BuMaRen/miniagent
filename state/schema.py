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

场景方通常不必手写上述 Python 类型树——StateSchema.from_yaml 能把同构的 YAML
翻译成 definition。YAML 里的写法:
    · 标量类型名写作字符串 "str" / "int" / "float" / "bool";"any" 对应 ANY。
    · dict 仍是 dict(对象),单元素 list 仍是同构列表([int]、[{...}])。
    · Optional 写作 `!optional <子描述符>`——这是这份 DSL 里唯一保留的 YAML 标签。
    · 除上面几个内置标量名与 "any" 外,任何裸字符串都会去 `types:` 声明的具名
      类型表里按名字查(见下)。OneOf 枚举也是靠这条规则引用的,不再需要单独的
      标签:在 `types:` 里声明一个 `{enum: [v1, v2, ...]}`,别处直接写它的名字。
上面 characters 片段对应的 YAML(character_role 是提前在 types: 里声明好的具名
枚举,见下一段):
    characters:
      - id: str
        name: str
        role: character_role
        status_log:
          - after_chapter: int
            state: str
场景方只需要维护这份 YAML 声明;把它编译成 definition、实例化 StateSchema 这件
"构造胶水"由 from_yaml 统一完成,不必再在场景代码里写 `StateSchema(name=...,
definition=...)`。

同一个子结构(或枚举)常常要在多处复用(如 story_bible.characters 的元素形状,
同时也是某个 Stage output_schema 的一部分)——顶层可加一个 `types:` 段落,给它
起名,别处直接写这个名字引用,而不是重复内联同一段结构:
    types:
      character_role:
        enum: [protagonist, antagonist, supporting]
      character:
        id: str
        name: str
        role: character_role
    definition:
      characters: [character]
`{enum: [...]}` 这个写法之所以不能直接写成裸列表 `role: [v1, v2, v3]`,是因为
裸列表的语法已经被"同构数组"占用了(`[X]` 表示"元素都长 X 的样子",且只能有
一个元素描述符)——`enum:` 这个具名 key 是刻意选来消歧义的,同时也是这份 DSL 里
除标量类型名之外的另一个保留字(对象里恰好只有一个叫这个名字的字段时会被当成
枚举声明而非字段,这是刻意接受的边界情况)。
`types:` 按书写顺序逐条编译:每条编译完就立刻写进"已就绪类型"表,所以裸名引用
只能指向*前面已经声明过*的类型——不支持前向引用或自引用,故意不做循环检测这类
额外复杂度。`definition:` 在整个 `types:` 都编译完之后才编译,这时全部具名类型
都已就绪。跨文件复用具名类型时,调用方可以:
    · 用 load_types(path) 单独编译某份 YAML 的 types: 段,拿到 {名字: 编译后的
      类型} 这张表;
    · 把这张表作为 `types=` 传给另一份 YAML 的 from_yaml(path, types=表),
      这份文件里的裸名引用就能查到表里的条目(以及自己 types: 段里更早声明的)。

StateSchema.to_prompt_example() 能把 definition 渲染成一段占位符 JSON 文本,
供 Stage 的 system prompt 里"输出格式"这类说明复用,不必手抄一份几乎同构的例子
（两处手写容易改一处、漏改另一处)。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


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


_PROMPT_SCALAR_EXAMPLES: dict[type, Any] = {str: "...", int: 0, float: 0.0, bool: True}


def _prompt_example(desc: Any) -> Any:
    """按描述符生成一份"占位符 JSON 值",供 StateSchema.to_prompt_example 使用。

    和 _empty 的取舍不同:这里的目标是给模型看的示例,不是合法的零值状态,所以
    OneOf 渲染成把候选项用 "|" 连起来的字符串(一眼看到取值范围),而不是 None。
    """
    if isinstance(desc, Optional):
        return _prompt_example(desc.inner)
    if isinstance(desc, OneOf):
        return "|".join(str(c) for c in desc.choices)
    if desc is ANY or isinstance(desc, _AnyType) or desc is None:
        return "..."
    if isinstance(desc, list):
        return [_prompt_example(desc[0])]
    if isinstance(desc, dict):
        return {k: _prompt_example(v) for k, v in desc.items()}
    if isinstance(desc, type):
        return _PROMPT_SCALAR_EXAMPLES.get(desc, "...")
    raise SchemaError(f"无法识别的 schema 描述符 {desc!r}")


class _YamlLoader(yaml.SafeLoader):
    """独立子类,避免 !optional 的构造器污染全局 yaml.SafeLoader。"""


class _RawOptional:
    """!optional 标签的解析期占位——inner 此时可能仍是待编译的类型名字符串。"""

    def __init__(self, inner: Any) -> None:
        self.inner = inner


def _construct_tagged_node(loader: yaml.SafeLoader, node: yaml.Node) -> Any:
    """构造标签节点自身携带的值(而非按标签二次派发)。

    !optional 的标签直接标在值节点上(如 `!optional int` 里,node 本身就是内容
    为 "int" 的标量节点),所以要按节点种类(标量/序列/映射)直接构造其内容,
    不能走 construct_object(node)——那会按 node.tag 重新查找构造器、落回这同一个
    标签,触发 PyYAML 的自递归保护而报错。
    """
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node, deep=True)
    raise SchemaError(f"无法识别的 YAML 节点种类: {node!r}")


_YamlLoader.add_constructor(
    "!optional", lambda loader, node: _RawOptional(_construct_tagged_node(loader, node))
)

_YAML_SCALAR_TYPES: dict[str, type] = {"str": str, "int": int, "float": float, "bool": bool}

# {enum: [v1, v2, ...]} 是 OneOf 的声明写法(取代旧的 !oneof 标签):单键 dict 靠
# 结构而不是标签消歧义,因为裸列表 `[X]` 的语法已经被"同构数组"占用了(见下方
# list 分支,且规定只能有一个元素描述符)。"enum" 是这份 DSL 除标量类型名之外的
# 另一个保留字——对象里恰好只有一个叫这个名字的字段时会被当成枚举声明而非字段,
# 这是刻意接受的边界情况(真实场景里几乎不会有对象长这样)。
_ENUM_KEY = "enum"


def _compile_yaml_node(node: Any, registry: dict[str, Any] | None = None) -> Any:
    """把 yaml.load(Loader=_YamlLoader) 解析出的原生结构编译成 definition 类型树。

    registry 是"已经编译好的具名类型"表(types: 段落按声明顺序逐条编译时随读随写、
    definition: 段落用编译完的整张表)。裸字符串只要不是内置标量名,就会去这张表
    按名字查——查不到即报错,引用只能指向前面已声明的类型,不支持前向引用或
    自引用。这一条引用规则同时覆盖"对象子结构复用"与"具名枚举引用"两种场景,
    不再需要 !type/!oneof 这类标签来区分。
    """
    if isinstance(node, _RawOptional):
        return Optional(_compile_yaml_node(node.inner, registry))
    if isinstance(node, str):
        if node == "any":
            return ANY
        if node in _YAML_SCALAR_TYPES:
            return _YAML_SCALAR_TYPES[node]
        if registry is not None and node in registry:
            return registry[node]
        raise SchemaError(
            f"未知的类型名 {node!r}(可用标量: str/int/float/bool/any,"
            "或 types: 中已声明的具名类型)"
        )
    if isinstance(node, list):
        if len(node) != 1:
            raise SchemaError(f"schema 列表须恰好一个元素描述符,得到 {len(node)} 个: {node!r}")
        return [_compile_yaml_node(node[0], registry)]
    if isinstance(node, dict):
        if set(node) == {_ENUM_KEY}:
            choices = node[_ENUM_KEY]
            if not isinstance(choices, list):
                raise SchemaError(f"enum 的取值须为列表,得到: {choices!r}")
            return OneOf(*choices)
        return {k: _compile_yaml_node(v, registry) for k, v in node.items()}
    raise SchemaError(f"无法识别的 schema YAML 节点: {node!r}")


def _compile_types_section(raw: dict[str, Any], base: dict[str, Any] | None) -> dict[str, Any]:
    """编译 YAML 顶层的 types: 段,产出一张"具名类型 -> 编译后类型"的表。

    base 是外部注入的已编译类型(用于跨文件复用,见 load_types);本文件 types:
    段的条目按书写顺序逐条编译并立即写入这张表,所以段内后面的条目可以引用前面
    的条目(乃至 base 里的条目),但不能反过来。
    """
    registry: dict[str, Any] = dict(base or {})
    for type_name, raw_type in (raw.get("types") or {}).items():
        registry[type_name] = _compile_yaml_node(raw_type, registry)
    return registry


def _load_raw_yaml(path: str | Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.load(f, Loader=_YamlLoader) or {}


def load_types(path: str | Path, types: dict[str, Any] | None = None) -> dict[str, Any]:
    """只编译某份 YAML 的 types: 段,返回 {类型名: 编译后的类型} 这张表。

    给"只想借用别处具名类型"的调用方用:该文件不必有 definition:(有也会被忽略)。
    典型用法是场景方的共享状态 schema(如 story_bible)在 types: 里声明了
    character/chapter 这类子结构,各 Stage 的 output_schema YAML 通过
    `StateSchema.from_yaml(path, types=load_types(共享 schema 路径))` 复用它们,
    而不必各自重复内联同一段结构。
    """
    raw = _load_raw_yaml(path)
    return _compile_types_section(raw, types)


@dataclass
class StateSchema:
    """状态结构声明。

    Attributes:
        name:       schema 名称(如 "story_bible")。
        definition: 字段定义(见模块 docstring 的类型树表示法);None 表示不校验。
    """

    name: str
    definition: Any = field(default=None)

    @classmethod
    def from_yaml(cls, path: str | Path, types: dict[str, Any] | None = None) -> "StateSchema":
        """从 YAML 文件加载一份 StateSchema(见模块 docstring 的 YAML DSL)。

        场景方只需按 DSL 写字段结构;把它编译成 definition、实例化 StateSchema
        这件"构造胶水"由这里统一做掉,场景代码不必再自己写
        `StateSchema(name=..., definition=...)`。

        YAML 顶层结构: {name: <schema 名称>, types: <具名类型表>,
        definition: <类型树>};name 缺省时取文件名(不含扩展名)。

        Args:
            types: 外部注入的已编译具名类型(见 load_types),供本文件的裸名引用
                跨文件复用;与本文件自己 types: 段的编译结果合并(本文件的
                同名条目优先)后,再用来编译 definition。
        """
        raw = _load_raw_yaml(path)
        name = raw.get("name") or Path(path).stem
        registry = _compile_types_section(raw, types)
        raw_definition = raw.get("definition")
        definition = (
            _compile_yaml_node(raw_definition, registry) if raw_definition is not None else None
        )
        return cls(name=name, definition=definition)

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

    def to_prompt_example(self) -> str:
        """把 definition 渲染成一段占位符 JSON 文本,供 prompt 里"输出格式"这类
        说明复用,不必在场景代码里再手抄一份几乎同构的例子(见模块 docstring)。
        definition 为 None 时返回 "{}"。
        """
        if self.definition is None:
            return "{}"
        return json.dumps(_prompt_example(self.definition), ensure_ascii=False, indent=2)

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


class SchemaRegistry:
    """"schema 名 -> StateSchema"的登记表,与 tools.registry.ToolRegistry 同构。

    为的是让 stages.yaml 里能用一个裸字符串引用 schema(`output_schema:
    critic_output`)——schema 本身是对象,YAML 里只写得下它的名字。
    """

    def __init__(self) -> None:
        self._schemas: dict[str, StateSchema] = {}

    def register(self, schema: StateSchema) -> bool:
        """登记一份 schema(key 取 schema.name);遇到重名返回 False,否则返回 True。"""
        if schema.name in self._schemas:
            return False
        self._schemas[schema.name] = schema
        return True

    def unregister(self, name: str) -> None:
        """移除一份 schema(重名登记前先卸载,或热替换时会用到)。"""
        self._schemas.pop(name, None)

    def names(self) -> list[str]:
        """已登记的全部 schema 名(排序后),用于报错时列出候选。"""
        return sorted(self._schemas)

    def load_dir(self, path: str | Path, types: dict[str, Any] | None = None) -> list[str]:
        """把一个目录下的全部 `*.yaml` 当作 schema 声明登记进来,返回登记到的名字。

        每个文件走已有的 StateSchema.from_yaml(path, types=types),名字取文件里的
        `name:`(缺省是文件名)。types 是跨文件复用的具名类型表(见 load_types),
        整目录共用一份——场景方各 Stage 的 output_schema 往往都要借用同一批子结构。

        重复调用是幂等的(已登记的同名 schema 跳过),因此场景方可以在每次
        build_node_registry 时无脑调一次。
        """
        directory = Path(path)
        if not directory.is_dir():
            raise SchemaError(f"schema 目录不存在: {directory}")
        loaded: list[str] = []
        for file in sorted(directory.glob("*.yaml")):
            schema = StateSchema.from_yaml(file, types=types)
            if self.register(schema):
                loaded.append(schema.name)
        return loaded

    def get(self, name: str) -> StateSchema:
        """按名取回 schema,缺失时给出带候选清单的清晰错误。"""
        try:
            return self._schemas[name]
        except KeyError:
            known = ", ".join(self.names()) or "<空>"
            raise SchemaError(f"schema {name!r} 未注册;已登记: {known}") from None


# 全局默认注册表,供场景方 load_dir()、engine/spec.py 解析 schema 名时共享。
default_registry = SchemaRegistry()
