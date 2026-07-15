"""State Store —— 通用共享状态(docs/framework-design.md §5)。

引擎只提供 get / patch / append / slice 的通用读写接口,字段语义由场景方提供
的 State Schema 决定。它把"一致性"从"依赖模型记住全文"变成"读写一份结构化数据"。

    StateStore   —— 抽象接口
    StateSchema  —— 场景方提供的字段定义与校验
    backends/    —— 具体存储后端(内存 / JSON 文件 / ...)
"""

from state.store import StateStore
from state.schema import StateSchema

__all__ = ["StateStore", "StateSchema"]
