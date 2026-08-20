from bumaren_agent_workflow.engine import Node, Stage, RunContext
from scenarios.example.schemas.state import (
    REQUIREMENT_DOC_PATH,
    REQUIREMENT_PARSE_OUTPUT_SCHEMA,
)


def build_requirement_parse_node(requirement_doc_path: str) -> Node:
    def _read(ctx: RunContext, inputs: dict) -> dict:
        with open(requirement_doc_path, "r", encoding="utf-8") as f:
            return {REQUIREMENT_DOC_PATH: f.read()}

    return Stage(
        name="requirement_parse",
        executor=_read,
        writes=[REQUIREMENT_DOC_PATH],
        output_schema=REQUIREMENT_PARSE_OUTPUT_SCHEMA,
    )
