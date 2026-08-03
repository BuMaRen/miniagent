"""novel —— 小说生成场景(见 scenarios/README.md、docs/workflow-design.md)。

本包是 docs/workflow-design.md 描述的工作流的具体落地:state_schema.yaml 定义故事
圣经,schemas//prompts//toolsets/ 是各 Stage 的契约/提示词/能力,stages.yaml 声明
节点、workflow.yaml 声明流程——这些 YAML 如何被装配成一个可运行的 Workflow,由
engine.scenario.Scenario 按目录约定统一负责(见其模块 docstring),本包只需要在这里
建一个 Scenario 实例。executors.py 是唯一还需要手写的 Python:纯函数 executor 与
节点包装工厂,详见其模块 docstring。run.py / offline_demo.py 是两种运行入口。
"""

from __future__ import annotations

from engine.scenario import Scenario

SCENARIO = Scenario.from_package(__name__)
