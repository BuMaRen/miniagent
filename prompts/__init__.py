"""Prompt 注册表 —— 把 Stage 的提示词从源码里挪到磁盘上的 *.prompt 文件。

与 tools/(工具)、state/(状态 schema)同级的框架构件:场景方把提示词写成
`prompts/xxx.prompt`,由 PromptRegistry 统一登记;stages.yaml 里用 "@xxx" 按名
引用(见 engine/spec.py)。
"""

from prompts.registry import (
    PromptError,
    PromptRegistry,
    default_registry,
    get,
    load_dir,
    parse_ref,
    register,
)

__all__ = [
    "PromptError",
    "PromptRegistry",
    "default_registry",
    "get",
    "load_dir",
    "parse_ref",
    "register",
]
