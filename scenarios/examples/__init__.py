"""examples —— 框架原语速查手册,不是一个真实场景。

目的和 novel/short 不一样:novel/short 是"用框架解决一个具体问题"的完整场景,
本包只演示"框架本身怎么用"——数据声明(State Schema)与四个控制流原语
(Sequence/Loop/ForEach/Checkpoint)+ Breaker,尤其是 Loop 的 continue_when
("continue":还要再来一轮)与 Breaker("break":提前结束循环)这两者的区别与配合。

不挂任何 LLM/Agent/ToolSet:所有 executor 都是普通函数,不需要 API Key,秒开秒跑,
方便把注意力集中在控制流本身。每个文件都可以独立运行:

    python -m scenarios.examples.state_schema
    python -m scenarios.examples.sequence_example
    python -m scenarios.examples.loop_example
    python -m scenarios.examples.foreach_example
    python -m scenarios.examples.breaker_example
    python -m scenarios.examples.checkpoint_example
    python -m scenarios.examples.combined_example

或者用 `python -m scenarios.examples.run` 一次性全部跑一遍。详见本目录 README.md。
"""
