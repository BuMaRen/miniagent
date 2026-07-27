"""novel —— 小说生成场景(见 scenarios/README.md、docs/workflow-design.md)。

本包是 docs/workflow-design.md 描述的工作流的具体落地:state_schema 定义故事圣经,
toolsets/ 是挂载到各 Stage 的能力,stages.py 把它们组装成 Stage,workflow.yaml +
workflow.py 拼出流程,run.py / offline_demo.py 是两种运行入口。
"""
