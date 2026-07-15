"""JsonFileStateStore —— JSON 文件后端(支持持久化与断点恢复)。

实现指导:
  - 复用 InMemoryStateStore 的路径寻址逻辑(可继承它,或组合一个内存实例);
    区别只在于每次写操作后把当前状态 flush 到磁盘。
  - 构造时若文件已存在则 load 进内存,实现"崩溃/暂停后从上次进度继续"。
  - 注意跨平台路径(Windows/Linux),不要把中间文件写死在 /tmp;
    路径应由调用方传入或取自运行配置。
  - 写盘建议原子化(先写临时文件再 rename),避免中途崩溃损坏状态文件。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from state.store import StateStore, StatePath
from state.schema import StateSchema


class JsonFileStateStore(StateStore):
    def __init__(self, path: str | Path, schema: StateSchema | None = None) -> None:
        self._path = Path(path)
        self._schema = schema
        self._data: dict[str, Any] = {}
        # TODO: 若 self._path 存在则读入 self._data(实现断点恢复)。

    def _flush(self) -> None:
        raise NotImplementedError  # TODO: 原子写入 self._data 到 self._path

    def get(self, path: StatePath, default: Any = None) -> Any:
        raise NotImplementedError

    def patch(self, path: StatePath, value: Any) -> None:
        raise NotImplementedError  # TODO: 更新内存后 self._flush()

    def append(self, path: StatePath, value: Any) -> None:
        raise NotImplementedError  # TODO: 更新内存后 self._flush()

    def slice(self, paths: list[StatePath]) -> dict[str, Any]:
        raise NotImplementedError

    def snapshot(self) -> dict[str, Any]:
        raise NotImplementedError

    def load(self, data: dict[str, Any]) -> None:
        raise NotImplementedError  # TODO: 载入后 self._flush()
