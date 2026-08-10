"""可编辑参考文件的通用加载逻辑 —— 供 trend.py / tags.py 共用。

月度风向、标签词表这类内容都是"运营方随时可整体替换、不需要碰代码"的纯
文本参考资料,格式与加载方式高度一致(见 trend.py 模块 docstring 里的取舍):
文件内 `<!-- ... -->` 包裹的维护说明会被过滤掉,不传给模型;文件不存在时
返回空字符串。抽成公共函数,避免每新增一份参考文件就抄一遍同样的正则。
"""

from __future__ import annotations

import re
from pathlib import Path

_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def load_reference_text(path: Path) -> str:
    """读取一份参考文件,过滤掉 <!-- ... --> 包裹的维护说明(可跨行)。

    每次调用都重新读文件(不缓存),运营方替换文件后下一次运行立即生效。
    文件不存在、被清空,或整篇都是维护说明时返回空字符串。
    """
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8")
    return _HTML_COMMENT_RE.sub("", text).strip()
