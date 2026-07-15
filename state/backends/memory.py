"""InMemoryStateStore —— 进程内字典后端(适合测试与短流程)。

实现指导:
  - 内部用一个嵌套 dict 保存状态,path 以 "." 分割逐层寻址;
    数字段视为列表下标(如 "chapters.0.title")。
  - get:  逐层下钻,任一层缺失返回 default。
  - patch:定位到父节点后写入;若目标与新值均为 dict 做浅合并,否则覆盖;
          中间缺失的层按需创建。
  - append:定位到列表(缺失则建空列表)后 append。
  - slice: 对每个 path 调 get,组装 {path: value}。
  - snapshot/load: deepcopy 进出,保证与外部隔离。
可选:构造时传入 StateSchema,在 patch/append 前做 validate_path 校验。
"""

from __future__ import annotations

from typing import Any

from state.store import StateStore, StatePath
from state.schema import StateSchema


class InMemoryStateStore(StateStore):
    def __init__(self, schema: StateSchema | None = None, initial: dict[str, Any] | None = None) -> None:
        self._schema = schema
        self._data: dict[str, Any] = initial or {}

    def get(self, path: StatePath, default: Any = None) -> Any:
        raise NotImplementedError  # TODO: 点分路径逐层下钻

    def patch(self, path: StatePath, value: Any) -> None:
        raise NotImplementedError  # TODO: 定位父节点 -> 浅合并/覆盖(可选先校验)

    def append(self, path: StatePath, value: Any) -> None:
        raise NotImplementedError  # TODO: 定位列表(缺失建空)-> append

    def slice(self, paths: list[StatePath]) -> dict[str, Any]:
        raise NotImplementedError  # TODO: {p: self.get(p) for p in paths}

    def snapshot(self) -> dict[str, Any]:
        raise NotImplementedError  # TODO: deepcopy(self._data)

    def load(self, data: dict[str, Any]) -> None:
        raise NotImplementedError  # TODO: self._data = deepcopy(data)
