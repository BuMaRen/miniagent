
from agent import Agent

local_agent = Agent(base_url="http://192.168.50.11:11434/v1", api_key="ollama", system_prompt="你是一个资深的系统架构师。所有输出内容必须通过调用 write_file 工具写入文件，禁止直接在对话中输出内容。")

local_agent.user_prompt(
	model="qwen3.5:4b",
	content="帮我设计一个系统，功能是读取 kuberntes 中的网络信息，下发给 pod 中的 sidecar， 作为路由规则。需要输出详细的设计方案到output目录中。",
	tools=local_agent.tools
)
