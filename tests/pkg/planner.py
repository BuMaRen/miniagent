import os

from llm.providers.openai.client import OpenAIClient
from planning.planner import Planner


def TestPlanner(cfg:str="") -> Planner:
    """
    Create a test instance of the Planner class.

    Args:
        cfg (str): Configuration string for the Planner.
    
    Example:
        content of file that cfg points to:
        ```json
        {
            "base_url": "******",
            "api_key": "******",
            "model": "******",
        }
        ```

    Returns:
        Planner: An instance of the Planner class.
    """
    # api_key = "ollama"
    # base_url = "http://192.168.50.11:11434/v1"
    # model = "qwen3.6:35b-a3b"
    
    api_key = os.getenv("TEST_API_KEY", "")
    base_url = os.getenv("TEST_BASE_URL", "")
    model = os.getenv("TEST_MODEL", "")
    if os.path.exists(cfg):
        with open(cfg, "r") as f:
            import json
            cfg_data = json.load(f)
            api_key = cfg_data.get("api_key", api_key)
            base_url = cfg_data.get("base_url", base_url)
            model = cfg_data.get("model", model)
    if any(v == "" for v in [api_key, base_url, model]):
        raise ValueError("API key, base URL, and model must be provided either in the config file or as environment variables.")

    client = OpenAIClient(
        api_key=api_key,
        base_url=base_url,
        model=model,
    )
    return Planner(llm_client=client, max_steps=10)