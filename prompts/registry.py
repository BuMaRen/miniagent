"""PromptRegistry —— "提示词名 -> 正文"的登记表。

与 tools.registry.ToolRegistry / engine.stage.ExecutorRegistry 同构:全局有一张
default_registry,场景方把提示词写成磁盘上的 `*.prompt` 文件、用 load_dir() 整目录
登记,之后在 stages.yaml 里用 "@名字" 按名引用(见 engine/spec.py)。

这张表只做两件事:登记(register/load_dir)与按名取回原文(get)。提示词之间要不要
共享片段、怎么拼接,是场景方自己的事——框架不提供"一段提示词里引用另一段"的展开
机制:那样的拼接逻辑要么该由场景方在准备 `*.prompt` 文件内容时自己做(写 Python
拼字符串,或者干脆把共享片段原样复制进每个用到它的文件——公共片段本就不常变,
复制几份也不必担心"改一处漏改别处"),要么根本不必存在。
"""

from __future__ import annotations

from pathlib import Path

# 提示词文件的扩展名;load_dir 只认这一种。
PROMPT_SUFFIX = ".prompt"

# 一行只有 "@名字" 时才视为引用;名字用与 Python 标识符相同的字符集,避免把
# "@张骞" 这类正文误判成引用。engine/spec.py 用它判断 stages.yaml 里 `prompt:`
# 字段写的是"按名去 PromptRegistry 查"还是字面量正文。
_REF_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")


class PromptError(ValueError):
    """提示词缺失等使用错误。属 ValueError 便于上层统一捕获。"""


def parse_ref(line: str) -> str | None:
    """一行是 "@名字" 形式的引用则返回名字,否则返回 None。"""
    stripped = line.strip()
    if len(stripped) < 2 or stripped[0] != "@" or stripped[1] == "@":
        return None
    name = stripped[1:]
    return name if set(name) <= _REF_CHARS else None


class PromptRegistry:
    def __init__(self) -> None:
        self._prompts: dict[str, str] = {}

    def register(self, name: str, text: str) -> bool:
        """登记一段提示词;遇到重名返回 False,否则返回 True。"""
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

    def get(self, name: str) -> str:
        """按名取回提示词正文,缺失时给出带候选清单的清晰错误。"""
        try:
            return self._prompts[name]
        except KeyError:
            known = ", ".join(self.names()) or "<空>"
            raise PromptError(f"提示词 {name!r} 未注册;已登记: {known}") from None


# 全局默认注册表,供场景方 load_dir()、engine/spec.py 解析 "@引用" 时共享。
default_registry = PromptRegistry()


def register(name: str, text: str) -> bool:
    """把一段提示词登记进 default_registry(等价于 default_registry.register)。"""
    return default_registry.register(name, text)


def load_dir(path: str | Path) -> list[str]:
    """把一个目录下的 `*.prompt` 登记进 default_registry。"""
    return default_registry.load_dir(path)


def get(name: str) -> str:
    """从 default_registry 按名取回提示词正文。"""
    return default_registry.get(name)
