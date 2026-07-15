"""工作流引擎核心(框架层,场景无关)。

对应 docs/framework-design.md 的 §3(Stage)、§6(控制流原语)、§7(Workflow 定义)。

这一层只负责"流程怎么串联、状态怎么读写、循环怎么退出",不含任何
"大纲""章节"之类的场景语义。场景方通过组合这里的原语来定义具体工作流。

主要导出:
    Stage       —— 最小执行单元(输入->输出的契约)
    Node        —— 所有可执行节点的统一协议(Stage 与各控制流原语都实现它)
    RunContext  —— 一次运行贯穿始终的上下文(持有 StateStore / Checkpoint 处理器等)
    Workflow    —— 由 Node 组成的完整流程,可执行
"""

from engine.stage import Stage, Node
from engine.context import RunContext
from engine.workflow import Workflow

__all__ = ["Stage", "Node", "RunContext", "Workflow"]
