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

import time

from llm.providers.openai.client import OpenAIClient
from memory.context import ConversationContext
from tools.registry import ToolRegistry
from tools.executor import ToolExecutor
from tools.builtin import fs_tools
from liuhe_tools import liuhe_tools
from core.agent import BaseAgent
from state import AgentRuntime


def new_client(model="qwen3:14b"):
    api_key = "ollama"
    base_url = "http://192.168.50.11:11434/v1"
    return OpenAIClient(api_key=api_key, base_url=base_url, model=model)


def new_tool():
    registry = ToolRegistry()
    for func, schema in fs_tools:
        registry.register(schema.name, func, schema)
    for func, schema in liuhe_tools:
        registry.register(schema.name, func, schema)
    executor = ToolExecutor(registry)
    return registry, executor


def new_context():
    system_prompt = """你需要帮用户处理输入的订单，最终答复各个物品和对应的采购数量。
    # 规则
    1. 每行内容必定包含若干对“物品列表和对应数量”的条目
    2. 物品和数量之间的分割符不确定，但“各”字眼的前面必定是物品，后面必定是数量
    3. 逗号、顿号、句号通常用于同一个条目中不同物品的分割
    4. 空格必定不会用来分割物品和数量
    5. 物品被编号成01~49的49个十进制的编号，超过49的数字必定为数量
    6. 物品的编号和数量均可能用中文表示
    7. 输入的非数字（包括中文数字）符号必定是分割符或者用于表示“各”
    
    # 套餐
    1. 十二生肖中的每一个生肖必定是一个套餐
    2. “尾”字以及前缀的10以下数字组合必定是一个套餐
    3. 大数、小数、单、双以及它们的组合字串也必定是一个套餐
    
    # 执行步骤
    1. 调用 id_generate 工具生成一个唯一的订单编号 uuid
    2. 判断每行中是否包含套餐，如果包含必须提取所有套餐调用 parse 工具解析，获得套餐对应的编号
    3. 根据步骤2取得的套餐和编号的对应关系，解析每行中所有物品和对应的数量，结果格式必须为“@@物品编号:数量 物品编号:数量 ...@@”，每个物品和数量之间用空格分隔，物品编号按升序排列
    4. 每行解析完后使用 uuid 调用 record 工具记录当前行和步骤3的解析结果
    5. 所有行解析完之后使用 uuid 调用 summary_record 工具生成最终的汇总结果返回给用户
    """
    return ConversationContext(
        client=new_client(),  # 用于压缩上下文的 LLMClient
        system_prompt=system_prompt,
        threshold=80,
    )


def new_agent():
    tools_registry, tools_executor = new_tool()
    return BaseAgent(
        llm_client=new_client(),
        tool_registry=tools_registry,
        tool_executor=tools_executor,
        memory=new_context(),
        router=None,
        planner=None,
        agent_state=AgentRuntime(),
    )


input = """23各二十11.23.35.11各三十
01到9号各10"""

ag = new_agent()
before = time.time()
answer = ag.run(input)
after = time.time()
print(answer)
print(f"Execution time: {after - before} seconds")
