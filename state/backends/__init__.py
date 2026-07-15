"""StateStore 的具体后端实现。

    InMemoryStateStore —— 进程内字典,适合测试与短流程。
    JsonFileStateStore —— 落盘为 JSON,适合需要跨进程持久化 / 断点恢复的运行。

新增后端(如数据库)只需实现 state.store.StateStore 接口即可,引擎与场景层无感。
"""

from state.backends.memory import InMemoryStateStore
from state.backends.json_file import JsonFileStateStore

__all__ = ["InMemoryStateStore", "JsonFileStateStore"]
