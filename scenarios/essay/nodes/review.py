from typing import Any

from engine.context import RunContext
from engine.stage import Node, Stage
from llm.client import LLMClient
from scenarios.essay import prompts
from scenarios.essay.nodes.common import annotate_word_counts, make_agent, merge_rejection
from scenarios.essay.schemas.state import (
    BRIEF_PATH,
    DRAFT_PATH,
    REVIEW_OUTPUT_SCHEMA,
    REVIEW_PATH,
)


def _review_executor(agent) -> Any:
    def _run(ctx: RunContext, inputs: dict) -> dict:
        outputs = agent.run(ctx, inputs)

        # 错别字修正会改变字数,审核节点返回的 draft 要重新统计,不能沿用
        # drafting 节点算过的旧值。
        total_words = annotate_word_counts(outputs.get(DRAFT_PATH, []))

        brief = inputs.get("state", {}).get(BRIEF_PATH) or {}
        ai_review = outputs.get(REVIEW_PATH) or {}
        rejected, feedback = merge_rejection(
            ai_rejected=bool(ai_review.get("rejected", False)),
            ai_feedback=ai_review.get("feedback", ""),
            min_words=brief.get("min_words", 0),
            max_words=brief.get("max_words", 10**9),
            total_words=total_words,
        )
        outputs[REVIEW_PATH] = {
            "rejected": rejected,
            "feedback": feedback,
        }
        return outputs

    return _run


def build_review_node(client: LLMClient) -> Node:
    """审核节点。只做两件事:错别字直接修正(不打回)、字数上下限由代码判定
    (nodes/common.merge_rejection)。AI 不再参与打回判定,ai_rejected/
    ai_feedback 恒为 False/"",最终 rejected 完全由字数是否达标决定。
    """
    agent = make_agent(
        client=client,
        system_prompt=prompts.REVIEW,
        output_schema=REVIEW_OUTPUT_SCHEMA,
    )

    return Stage(
        name="review",
        executor=_review_executor(agent),
        reads=[BRIEF_PATH, DRAFT_PATH],
        writes=[DRAFT_PATH, REVIEW_PATH],
        output_schema=REVIEW_OUTPUT_SCHEMA,
    )
