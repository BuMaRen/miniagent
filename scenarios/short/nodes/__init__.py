"""short 场景的各个 Node,按业务分组拆成一个模块一组,外加一份公用组件
(common.py)。谁需要串成流程,去 scenarios/short/workflow.py 看——那里是唯一
知道 Sequence/Loop/ForEach 怎么套的地方,这里每个模块只管"这个 Node 是什么"。
"""
