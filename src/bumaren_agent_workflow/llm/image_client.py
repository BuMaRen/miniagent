"""ImageClient —— 图像生成客户端抽象接口(扩展点)。

与 llm/client.py 的 LLMClient 同一层级、同一心智模型:场景方只依赖这个接口,
真正接哪家图像生成 API 由使用方后续实现一个具体子类并替换掉工厂函数即可,
调用方代码(如 scenarios/essay 的封面生成节点)不需要再改。

本次只提供接口 + 一个"未配置"占位实现(NotConfiguredImageClient)。占位实现
的 generate() 直接抛 NotImplementedError——这不是 bug,是刻意的:调用方(见
scenarios/essay/nodes/cover.py)走 engine 的正常失败续跑路径(WorkflowFailure),
以后接入真图像 Provider 后重跑同一个 run 即可只从封面这一步续上,不需要重新
生成正文。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ImageResult:
    """一次图像生成的标准化返回。

    Attributes:
        url:         图像的可访问地址(远程 Provider 常见形态)。
        data_base64: 图像的 base64 编码内容(本地/同步返回二进制的 Provider 常见形态)。
                     url 和 data_base64 至少有一个非 None。
        mime_type:   图像 MIME 类型。
        meta:        Provider 附带的其它元信息(如 revised_prompt、seed 等),可选。
    """

    url: str | None = None
    data_base64: str | None = None
    mime_type: str = "image/png"
    meta: dict[str, Any] = field(default_factory=dict)


class ImageClient(ABC):
    """图像生成客户端接口。"""

    @abstractmethod
    def generate(self, prompt: str, **params: Any) -> ImageResult:
        """根据文本提示生成一张图像。

        Args:
            prompt: 图像描述(通常是场景方已经用 LLMClient 生成好的一段视觉文案)。
            params: Provider 相关参数(尺寸、风格、seed 等)。
        """


class NotConfiguredImageClient(ImageClient):
    """默认占位实现:尚未接入具体图像 Provider 时的兜底,generate() 直接报错。

    不是"挂起等以后再答"的意思(与 engine.primitives.checkpoint 的
    CheckpointHandler 必需性同理)——缺失就是一次配置错误,交给调用方的正常
    失败路径处理。
    """

    def generate(self, prompt: str, **params: Any) -> ImageResult:
        raise NotImplementedError(
            "封面图像生成尚未接入具体 Provider:实现 ImageClient 的一个子类"
            "(参考 llm/providers/ 下 LLMClient 的写法),在调用方(如"
            "scenarios/essay/run.py 或 site/server.py)的 image_client 工厂函数里"
            "换成该实现即可,不需要改动 workflow/nodes 代码。"
        )
