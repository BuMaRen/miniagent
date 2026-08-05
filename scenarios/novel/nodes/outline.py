"""大纲生成与评审(3.4/3.5)—— outline_loop 的 body,以及大纲人工复核。

大纲生成与修订是同一个节点:游标为空就是生成,游标里带着上一轮的评审意见就是
修订(见 prompts.OUTLINE_GENERATION)。
"""

from __future__ import annotations

from engine.primitives.checkpoint import Checkpoint
from engine.primitives.loop import loop_cursor_path
from engine.stage import Stage
from llm.client import LLMClient
from state.schema import StateSchema

from scenarios.novel import prompts
from scenarios.novel.nodes.common import (
    CHARACTERS_PATH,
    CHAPTERS_PATH,
    CRITIC_OUTPUT_SCHEMA,
    FORESHADOWING_PATH,
    META_PATH,
    WORLD_PATH,
    make_agent,
)
from scenarios.novel.state_schema import CHAPTER, FORESHADOWING
from scenarios.novel.toolsets.research import RESEARCH_TOOLSET

# Loop 的名字,同时用于拼出游标路径——workflow.py 组装 Loop(name=OUTLINE_LOOP_NAME,
# ...) 时也要用这个名字,两处共用一份常量,不会各写一遍。
OUTLINE_LOOP_NAME = "outline_loop"
OUTLINE_LOOP_LAST_PATH = loop_cursor_path(OUTLINE_LOOP_NAME)

OUTLINE_GENERATION_OUTPUT_SCHEMA = StateSchema(
    "outline_generation_output",
    {
        CHAPTERS_PATH: [CHAPTER],
        FORESHADOWING_PATH: [FORESHADOWING],
        META_PATH: {"title": str, "logline": str},
    },
)


def build_outline_generation_stage(client: LLMClient) -> Stage:
    agent = make_agent(
        client,
        prompts.OUTLINE_GENERATION,
        toolsets=(RESEARCH_TOOLSET,),
        output_schema=OUTLINE_GENERATION_OUTPUT_SCHEMA,
    )
    return Stage(
        name="outline_generation",
        executor=agent.run,
        reads=[OUTLINE_LOOP_LAST_PATH, META_PATH, CHARACTERS_PATH, WORLD_PATH],
        writes=[CHAPTERS_PATH, FORESHADOWING_PATH, META_PATH],
        output_schema=OUTLINE_GENERATION_OUTPUT_SCHEMA,
    )


def build_outline_critic_stage(client: LLMClient) -> Stage:
    agent = make_agent(client, prompts.OUTLINE_CRITIC, output_schema=CRITIC_OUTPUT_SCHEMA)
    return Stage(
        name="outline_critic",
        executor=agent.run,
        reads=[META_PATH, CHARACTERS_PATH],
        output_schema=CRITIC_OUTPUT_SCHEMA,
    )


def build_confirm_outline_checkpoint() -> Checkpoint:
    return Checkpoint(
        name="confirm_outline",
        prompt="大纲已通过 AI 评审,请确认是否按此大纲进入逐章撰写;不通过请给出修改意见。",
        resume_input_schema=CRITIC_OUTPUT_SCHEMA,
    )
