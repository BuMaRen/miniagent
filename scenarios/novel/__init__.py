"""novel —— 小说生成场景(见 scenarios/README.md、docs/workflow-design.md)。

本包是 docs/workflow-design.md 描述的工作流的具体落地:state_schema.py 定义故事
圣经,toolsets/ 是各 Stage 挂载的能力,prompts.py 是流程侧提示词,nodes/ 下按
业务分组给每个节点提供 build_xxx_stage() 函数("这个节点是什么"),workflow.py
的 build_workflow() 把它们拼成可执行的 Workflow("这些节点怎么串",见其模块
docstring)。run.py / offline_demo.py 是两种运行入口。
"""
