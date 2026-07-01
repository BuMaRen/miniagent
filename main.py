# 框架入口示例文件，展示如何组装和使用各模块。
#
# 步骤：
#   1. 从环境变量读取 API_KEY、BASE_URL、MODEL 等配置
#   2. 创建 AgentConfig，配置 system_prompt、max_steps 等参数
#   3. 实例化 LLMClient（根据配置选择 OpenAIClient 或 AnthropicClient）
#   4. 创建 ToolRegistry，注册需要的内置工具（fs_tools、web_tools 等）
#   5. 实例化 Agent，传入上述组件
#   6. （可选）注册 LifecycleHooks，如打印工具调用日志
#   7. 进入交互循环：读取用户输入 -> 调用 agent.run(user_input) -> 打印结果
#
# 示例用法：
#   python main.py
#   > 帮我搜索 Python asyncio 的最新文档并总结要点
