"""从 workflow.yaml 拼出可执行的 Workflow(docs/framework-design.md §7)。

workflow.yaml 只是纯结构,不认识 "section_drafting" 这些名字具体是什么 ——
那是 stages.build_node_registry() 的职责。这里把两者接起来。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from engine.workflow import Workflow
from scenarios.short.stages import ClientFactory, build_node_registry
from scenarios.short.state_schema import SHORT_STORY_SCHEMA

WORKFLOW_YAML_PATH = Path(__file__).with_name("workflow.yaml")


def load_workflow_spec(path: Path | str = WORKFLOW_YAML_PATH) -> dict[str, Any]:
    """读取 workflow.yaml,返回 Workflow.from_spec 期望的 dict 结构。"""
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_workflow(
    client_factory: ClientFactory, spec_path: Path | str = WORKFLOW_YAML_PATH
) -> Workflow:
    """组装一个可运行的 short_story_generation Workflow。

    Args:
        client_factory: 传给 stages.build_node_registry 的 LLMClient 工厂,决定
            每个需要 LLM 的节点用哪个 client。
        spec_path: workflow.yaml 的路径,默认取本包内的那份。
    """
    spec = load_workflow_spec(spec_path)
    stage_models = Workflow.resolve_stage_models(spec)
    registry = build_node_registry(client_factory, stage_models)
    workflow = Workflow.from_spec(spec, registry)
    # from_spec 只透传 spec 里的字符串引用,这里补上真正的 StateSchema 实例。
    workflow.state_schema = SHORT_STORY_SCHEMA
    return workflow
