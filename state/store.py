"""StateStore —— 通用共享状态接口(docs/framework-design.md §5)。

引擎不关心 path 指向的字段语义,只提供统一的读写原语。所有后端(内存、
JSON 文件等)实现同一接口,便于替换与测试。path 采用点分路径寻址,如
"story_bible.characters" 或 "story_bible.chapters.0.title"。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

StatePath = str


class StateStore(ABC):
    """结构化共享状态的抽象接口。

    设计要点(见 §5):
      - patch  用于增量更新,不重写全量。
      - append 用于追加型字段(日志/历史),不覆盖历史。
      - slice  用于按需切片读取,控制注入 LLM 上下文的状态规模——
               这是长文本一致性与上下文成本控制的关键。
    """

    @abstractmethod
    def get(self, path: StatePath, default: Any = None) -> Any:
        """按路径读取单个值,缺失时返回 default。"""

    @abstractmethod
    def patch(self, path: StatePath, value: Any) -> None:
        """增量更新指定路径的值(dict 语义为浅合并,标量为覆盖)。"""

    @abstractmethod
    def append(self, path: StatePath, value: Any) -> None:
        """向指定路径的列表字段追加一个元素(路径不存在则创建空列表)。"""

    @abstractmethod
    def slice(self, paths: list[StatePath]) -> dict[str, Any]:
        """一次性取回多个路径,组装成 {path: value} 字典。

        Stage 用它按 reads 声明只取相关切片,而非注入全量状态。
        """

    @abstractmethod
    def snapshot(self) -> dict[str, Any]:
        """返回当前完整状态的深拷贝,用于持久化 / Checkpoint 恢复 / 调试。"""

    @abstractmethod
    def load(self, data: dict[str, Any]) -> None:
        """从一份快照恢复全量状态。"""
