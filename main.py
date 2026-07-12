from custom.liuhe_agent import LiuHeAgent
from llm import OpenAIClient

client = OpenAIClient(
    model="qwen3.7-plus",
    api_key="api_key",
    base_url="base_url",
)
agent = LiuHeAgent(client=client)  # Replace `None` with an actual LLMClient instance

from input import t20260712, test_prompt
agent.run(t20260712)