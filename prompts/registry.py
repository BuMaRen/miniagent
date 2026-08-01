"""PromptRegistry —— "提示词名 -> 正文"的登记表,以及正文里的引用展开。

与 tools.registry.ToolRegistry / engine.stage.ExecutorRegistry 同构:全局有一张
default_registry,场景方把提示词写成磁盘上的 `*.prompt` 文件、用 load_dir() 整目录
登记,之后在 stages.yaml 里用 "@名字" 按名引用(见 engine/spec.py)。

## 为什么要"展开",而不是一个文件一段完整提示词

同一段话常常要出现在多段提示词里(小说场景的风格基调 style_guide 就同时出现在 7
个 Stage 的 system prompt 里)。所以正文里**独占一行**的 `@其它提示词名` 会被替换成
那段提示词的正文(递归展开,带环检测):

    你负责小说创作流程中的"立意扩展"阶段。

    @style_guide

    输入会包含题材(topic)……

只认"独占一行"这一种写法,是为了不必区分"这个 @ 是引用还是正文里恰好出现的字符"
——行内的 @ 一律当普通文本。确实需要单起一行写字面量 @xxx 时,写成 `@@xxx`。

## 占位符(placeholders)

有些片段在登记期还不知道内容,只有用到它的那个 Stage 才知道——典型的是"输出格式"
一节要贴的 output_schema 示例。这类片段由调用方在取用时通过 placeholders 传入:

    prompts.get("concept_expansion_prompt",
                {"output_schema_example": schema.to_prompt_example()})

placeholders 与已登记的提示词共用同一套 `@名字` 语法与同一个命名空间(placeholders
优先),所以提示词作者不需要知道某个名字是"别的提示词"还是"调用方现算的片段"。
"""

from __future__ import annotations

from pathlib import Path

# 提示词文件的扩展名;load_dir 只认这一种。
PROMPT_SUFFIX = ".prompt"

# 一行只有 "@名字" 时才视为引用;名字用与 Python 标识符相同的字符集,避免把
# "@张骞" 这类正文误判成引用。
_REF_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")


class PromptError(ValueError):
    """提示词缺失、循环引用等使用错误。属 ValueError 便于上层统一捕获。"""


def parse_ref(line: str) -> str | None:
    """一行是 "@名字" 形式的引用则返回名字,否则返回 None。

    engine/spec.py 也用它判断 stages.yaml 里的 `prompt:` 写的是引用还是字面量,
    保证两处对"什么算引用"的判断完全一致。
    """
    stripped = line.strip()
    if len(stripped) < 2 or stripped[0] != "@" or stripped[1] == "@":
        return None
    name = stripped[1:]
    return name if set(name) <= _REF_CHARS else None


class PromptRegistry:
    def __init__(self) -> None:
        self._prompts: dict[str, str] = {}

    def register(self, name: str, text: str) -> bool:
        """登记一段提示词;遇到重名返回 False,否则返回 True。

        正文原样存放,引用留到 get() 时才展开——登记顺序因此无关紧要,
        style_guide 晚于引用它的提示词登记也没问题。
        """
        if name in self._prompts:
            return False
        self._prompts[name] = text
        return True

    def unregister(self, name: str) -> None:
        """移除一段提示词(重名登记前先卸载,或热替换时会用到)。"""
        self._prompts.pop(name, None)

    def names(self) -> list[str]:
        """已登记的全部提示词名(排序后),用于报错时列出候选。"""
        return sorted(self._prompts)

    def load_dir(self, path: str | Path) -> list[str]:
        """把一个目录下的全部 `*.prompt` 登记进来,返回登记到的名字列表。

        名字取文件名(不含扩展名):`prompts/style_guide.prompt` -> "style_guide"。
        重复调用是幂等的(已登记的同名文件跳过),因此场景方可以在每次
        build_node_registry 时无脑调一次,不必自己记"加载过没有"。
        """
        directory = Path(path)
        if not directory.is_dir():
            raise PromptError(f"提示词目录不存在: {directory}")
        loaded: list[str] = []
        for file in sorted(directory.glob(f"*{PROMPT_SUFFIX}")):
            if self.register(file.stem, file.read_text(encoding="utf-8")):
                loaded.append(file.stem)
        return loaded

    def raw(self, name: str) -> str:
        """按名取回**未展开**的原始正文,缺失时给出带候选清单的清晰错误。"""
        try:
            return self._prompts[name]
        except KeyError:
            known = ", ".join(self.names()) or "<空>"
            raise PromptError(f"提示词 {name!r} 未注册;已登记: {known}") from None

    def get(self, name: str, placeholders: dict[str, str] | None = None) -> str:
        """按名取回**展开后**的正文(见模块 docstring)。"""
        return self._expand(self.raw(name), placeholders or {}, [name])

    def render(self, text: str, placeholders: dict[str, str] | None = None) -> str:
        """展开一段**字面量**正文里的引用。

        供"提示词直接写在 stages.yaml 里、没有单独成文件"的情况使用——它同样可以
        引用 @style_guide 这类已登记片段。
        """
        return self._expand(text, placeholders or {}, [])

    def _expand(self, text: str, placeholders: dict[str, str], stack: list[str]) -> str:
        lines: list[str] = []
        for line in text.splitlines():
            name = parse_ref(line)
            if name is None:
                # "@@xxx" 是转义写法:还原成字面量的 "@xxx"。
                lines.append(line.replace("@@", "@", 1) if line.strip()[:2] == "@@" else line)
                continue
            if name in placeholders:
                lines.append(placeholders[name])
                continue
            if name in stack:
                chain = " -> ".join([*stack, name])
                raise PromptError(f"提示词循环引用: {chain}")
            lines.append(self._expand(self.raw(name), placeholders, [*stack, name]))
        return "\n".join(lines)


# 全局默认注册表,供场景方 load_dir()、engine/spec.py 解析 "@引用" 时共享。
default_registry = PromptRegistry()


def register(name: str, text: str) -> bool:
    """把一段提示词登记进 default_registry(等价于 default_registry.register)。"""
    return default_registry.register(name, text)


def load_dir(path: str | Path) -> list[str]:
    """把一个目录下的 `*.prompt` 登记进 default_registry。"""
    return default_registry.load_dir(path)


def get(name: str, placeholders: dict[str, str] | None = None) -> str:
    """从 default_registry 按名取回展开后的提示词正文。"""
    return default_registry.get(name, placeholders)
