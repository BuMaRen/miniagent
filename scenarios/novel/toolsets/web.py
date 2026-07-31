"""网络访问工具集 —— 面向"用户能提供的只有静态资料,考据库覆盖不到"的场景。

与 research.py 里手工整理的封闭知识库不同,这里的两个工具会真正发起 HTTP
请求,因此有几点跟 research.py 相反:
- 结果不确定、随时间变化,不能假设同参数重复调用结果不变,不要把它们标成
  deterministic(参见 TodoList「静态提示查询」那条的讨论)。
- 依赖外部网络可用性;失败时把原因整理成文本回给模型,而不是让异常裸着抛
  出去(ToolExecutor 本身也会兜底 try/except,这里的 try/except 是为了给出
  比裸异常更有用、更不容易被模型误判为"信息不存在"的提示)。

搜索后端选型踩过一次坑:最初接的是免 Key 的 DuckDuckGo HTML 端点
(html.duckduckgo.com),但沙箱/机房出口 IP 会被其反爬机制拦成人机验证页
(anomaly.js 验证码挑战),返回 HTTP 202 却拿不到真实结果,不可用。改用
维基百科官方 Search/Extracts API(zh.wikipedia.org/w/api.php)—— 免 Key、
无反爬、返回结构化 JSON/纯文本,更适合这个历史考据场景;代价是覆盖面
局限于维基百科词条,不是通用网页搜索。如果之后要接 Tavily/Bing 等商业
搜索 API 做通用网页搜索,可以照 run.py 里"按环境变量选 provider"的套路,
在环境变量存在时优先使用。

这是一版最小可用原型:先在 scenarios/novel/toolsets 下验证"联网查证"这条
路能不能打通,还没有接入任何 workflow 的 toolsets=(...)。
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import unquote

import httpx

from agent.toolset import ToolSet

_TIMEOUT = 10.0
_UA = "miniagent-research-bot/0.1 (educational novel-writing tool)"
_WIKI_API = "https://zh.wikipedia.org/w/api.php"
_WIKI_ARTICLE_RE = re.compile(r"^https?://zh\.wikipedia\.org/wiki/(?P<title>[^#?]+)")


class _TextExtractor(HTMLParser):
    """从 HTML 中粗略抽取可读正文:跳过 script/style,把标签替换为空白分隔。"""

    _SKIP_TAGS = {"script", "style", "noscript"}

    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self.chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and data.strip():
            self.chunks.append(data.strip())


def _extract_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    return "\n".join(parser.chunks)


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n...(已截断,原文共 {len(text)} 字)"


def web_search(query: str, max_results: int = 5) -> str:
    """联网搜索中文维基百科词条(免 API Key),用于查证本地考据库未收录的信息。

    只覆盖维基百科,不是通用网页搜索;返回的是词条标题、摘要片段与链接,
    结果可能随时间变化,查不到不代表现实中不存在——网络异常时会直接说明
    原因。想看某个词条的完整正文,把返回的链接传给 fetch_url。

    Args:
        query: 搜索关键词。
        max_results: 最多返回的结果条数,默认 5。
    """
    try:
        resp = httpx.get(
            _WIKI_API,
            params={
                "action": "query",
                "list": "search",
                "srsearch": query,
                "srlimit": max_results,
                "format": "json",
            },
            headers={"User-Agent": _UA},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        results = resp.json().get("query", {}).get("search", [])
    except (httpx.HTTPError, ValueError) as e:
        return f"搜索请求失败({e!r}),不代表该信息不存在,可稍后重试。"

    if not results:
        return f"未搜到与 '{query}' 相关的维基百科词条,换个更常见的关键词试试。"

    _tag_re = re.compile(r"<[^>]+>")
    lines = []
    for item in results:
        title = item["title"]
        snippet = _tag_re.sub("", item.get("snippet", "")).strip()
        url = f"https://zh.wikipedia.org/wiki/{title.replace(' ', '_')}"
        lines.append(f"- {title}\n  {url}\n  {snippet}")
    return "\n".join(lines)


def fetch_url(url: str, max_chars: int = 4000) -> str:
    """抓取指定网址并返回正文纯文本,用于查看 web_search 结果的详情。

    对维基百科词条网址(zh.wikipedia.org/wiki/...)会走维基官方 Extracts API
    拿干净正文;其余网址走通用 HTML 抓取 + 去标签,可能夹带导航栏等噪音。

    Args:
        url: 要抓取的完整网址,需以 http:// 或 https:// 开头。
        max_chars: 返回文本的最大字符数,超出部分会被截断,默认 4000。
    """
    if not url.startswith(("http://", "https://")):
        return f"无效的 url: {url!r},必须以 http:// 或 https:// 开头。"

    wiki_match = _WIKI_ARTICLE_RE.match(url)
    if wiki_match:
        title = unquote(wiki_match.group("title")).replace("_", " ")
        try:
            resp = httpx.get(
                _WIKI_API,
                params={
                    "action": "query",
                    "prop": "extracts",
                    "explaintext": 1,
                    "titles": title,
                    "format": "json",
                },
                headers={"User-Agent": _UA},
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            pages = resp.json().get("query", {}).get("pages", {})
            extract = next(iter(pages.values()), {}).get("extract", "")
        except (httpx.HTTPError, ValueError) as e:
            return f"抓取失败({e!r})。"
        if not extract:
            return f"未找到词条 '{title}' 的正文(可能已被重定向或删除)。"
        return _truncate(extract, max_chars)

    try:
        resp = httpx.get(
            url, headers={"User-Agent": _UA}, timeout=_TIMEOUT, follow_redirects=True
        )
        resp.raise_for_status()
    except httpx.HTTPError as e:
        return f"抓取失败({e!r})。"
    return _truncate(_extract_text(resp.text), max_chars)


WEB_TOOLSET = ToolSet.from_funcs("web_toolset", [web_search, fetch_url])
