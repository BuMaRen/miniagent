"""StateSchema —— 场景方提供的状态字段定义与校验。

引擎自身不含任何字段语义;场景方通过一份 StateSchema 声明"这份共享状态长什么样"
(小说场景的实例见 docs/story-bible-schema.md)。Schema 用于:初始化空状态、
校验 patch/append 写入是否合法、以及 Stage 的 input/output 契约校验。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class StateSchema:
    """状态结构声明。

    实现方式不限定:可以薄封装 pydantic / jsonschema,也可以是自定义的字段树。
    这里只约定引擎需要用到的能力。

    Attributes:
        name:       schema 名称(如 "story_bible")。
        definition: 具体的字段定义(交由所选校验库解析)。
    """

    name: str
    definition: Any = field(default=None)

    def empty(self) -> dict[str, Any]:
        """构造一个符合 schema 的空初始状态(用于新一次运行的起点)。"""
        # TODO: 依据 definition 生成带默认值的空结构。
        raise NotImplementedError

    def validate(self, data: dict[str, Any]) -> None:
        """校验一份数据是否符合 schema;不符合应抛出带清晰路径的错误。"""
        # TODO: 委托给底层校验库,或自行遍历 definition 校验。
        raise NotImplementedError

    def validate_path(self, path: str, value: Any) -> None:
        """校验对某个路径的写入是否合法(供 StateStore.patch/append 调用)。"""
        raise NotImplementedError
