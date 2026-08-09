from engine.context import RunContext
from engine.stage import Node, Stage
from llm.client import LLMClient
from llm.image_client import ImageClient
from scenarios.essay import prompts
from scenarios.essay.nodes.common import make_agent
from scenarios.essay.schemas.state import (
    BRIEF_PATH,
    COVER_BRIEF_OUTPUT_SCHEMA,
    COVER_BRIEF_PATH,
    COVER_IMAGE_OUTPUT_SCHEMA,
    COVER_IMAGE_PATH,
    PLAN_PATH,
)


def build_cover_brief_node(client: LLMClient) -> Node:
    """封面文案节点:产出一段视觉描述文案(不是图像本身),供下一步喂给图像生成。"""
    agent = make_agent(
        client=client,
        system_prompt=prompts.COVER_BRIEF,
        output_schema=COVER_BRIEF_OUTPUT_SCHEMA,
    )

    return Stage(
        name="cover_brief",
        executor=agent.run,
        reads=[PLAN_PATH, BRIEF_PATH],
        writes=[COVER_BRIEF_PATH],
        output_schema=COVER_BRIEF_OUTPUT_SCHEMA,
    )


def build_cover_image_node(image_client: ImageClient) -> Node:
    """封面图像节点:调用 ImageClient 把文案变成真正的图像。

    image_client 是占位实现(NotConfiguredImageClient)时,这一步会抛
    NotImplementedError,workflow 走正常失败续跑路径——正文与封面文案已经
    落盘,以后接入真图像 Provider 后重跑同一个 run 会只从这一步续上,不需要
    重新生成正文(见 llm/image_client.py 模块 docstring)。
    """

    def _run(ctx: RunContext, inputs: dict) -> dict:
        brief = inputs.get("state", {}).get(COVER_BRIEF_PATH, "")
        result = image_client.generate(brief)
        image = {
            "url": result.url or (f"data:{result.mime_type};base64,{result.data_base64}" if result.data_base64 else ""),
            "note": str(result.meta) if result.meta else "",
        }
        return {COVER_IMAGE_PATH: image}

    return Stage(
        name="cover_image",
        executor=_run,
        reads=[COVER_BRIEF_PATH],
        writes=[COVER_IMAGE_PATH],
        output_schema=COVER_IMAGE_OUTPUT_SCHEMA,
    )
