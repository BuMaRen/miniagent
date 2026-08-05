"""各节点按业务分组:每个模块提供 build_xxx_stage() 函数,负责"这一个节点是
什么"(谁执行、读写哪些状态切片、输出契约)。"这些节点怎么串"是
scenarios/novel/workflow.py 的职责。
"""
