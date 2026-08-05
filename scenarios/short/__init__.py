"""short —— 短篇网络小说生成场景(8000-10000 字)。

与 scenarios/novel 的区别有三点:

1. **内容无关**:流程侧的 prompt(prompts.py)只讲"怎么写"(节奏、爽点、语言
   底线、输出契约),不含任何题材、人名、朝代、世界观。要写什么完全由用户在
   brief.yaml 里给出,经 brief.py 校验后落进 State 的 short_story.brief,再由各
   Stage 以 reads 注入。换题材不需要改流程侧的任何一个字。
2. **不设人工断点**:全程无 Checkpoint,Loop 超限一律 accept_last_version,
   跑完直接落地成品。质量把关改由"确定性体检 + LLM Critic"两道关卡承担。
3. **更短的流水线**:5 个 LLM 节点 + 2 个纯函数节点(见 workflow.py)。
"""
