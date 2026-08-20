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

import json
from pathlib import Path
from typing import Any

from bumaren_agent_workflow.state.backends.memory import InMemoryStateStore
from bumaren_agent_workflow.state.store import StateStore, StatePath
from bumaren_agent_workflow.state.schema import StateSchema


class JsonFileStateStore(StateStore):
    """组合一个 InMemoryStateStore 做路径寻址,每次写操作后把全量状态 flush 到磁盘。"""

    def __init__(self, path: str | Path, schema: StateSchema | None = None) -> None:
        self._path = Path(path)
        initial = self._read_from_disk()
        self._store = InMemoryStateStore(schema=schema, initial=initial)

    def _read_from_disk(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        with self._path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def _flush(self) -> None:
        # 先写临时文件再 rename:rename 在同一文件系统内是原子操作,
        # 避免进程在写盘中途崩溃导致状态文件损坏成半份 JSON。
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_name(self._path.name + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(self._store.snapshot(), f, ensure_ascii=False, indent=2)
        tmp_path.replace(self._path)

    def get(self, path: StatePath, default: Any = None) -> Any:
        return self._store.get(path, default)

    def patch(self, path: StatePath, value: Any) -> None:
        self._store.patch(path, value)
        self._flush()

    def append(self, path: StatePath, value: Any) -> None:
        self._store.append(path, value)
        self._flush()

    def slice(self, paths: list[StatePath]) -> dict[str, Any]:
        return self._store.slice(paths)

    def snapshot(self) -> dict[str, Any]:
        return self._store.snapshot()

    def load(self, data: dict[str, Any]) -> None:
        self._store.load(data)
        self._flush()
