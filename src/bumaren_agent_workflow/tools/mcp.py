"""MCP(Model Context Protocol)适配层。

把外部 MCP Server(如 `npx @playwright/mcp`)的工具接入本框架的工具系统:
MCP 官方 SDK 是 async 的,而 Agent/ToolExecutor 驱动的 agentic loop 是同步的
(见 agent/agent.py 的 run()),这里用一个专属后台线程常驻一个 event loop 做
同步桥接,让远程 MCP 工具能转成本框架的 ToolSchema、包装成同步可调用函数,
最终打包成一个可直接 `agent.load_toolset()` 的 ToolSet——对 Agent 而言,一个
MCP 工具和一个本地 @tool 函数没有区别。

用法(以 `npx @playwright/mcp` 为例):

    from bumaren_agent_workflow.tools.mcp import MCPServer

    with MCPServer.stdio("playwright", command="npx", args=["@playwright/mcp@latest"]) as server:
        agent.load_toolset(server.toolset())
        ...  # agent.run(...)

不用 with 也可以手动管理连接生命周期:

    server = MCPServer.stdio("playwright", command="npx", args=["@playwright/mcp@latest"])
    server.connect()
    agent.load_toolset(server.toolset())
    ...
    server.close()

当前只支持 stdio transport(子进程),这是本地/CLI 场景(含 `@playwright/mcp`)
最常见的接入方式;远程 HTTP/SSE MCP Server 需要时可以照这个模式再加一个
构造入口,底层的后台 loop 桥接与 ToolSet 打包逻辑可以直接复用。
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import threading
from contextlib import AsyncExitStack
from typing import Any, Callable

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult, TextContent, Tool

from bumaren_agent_workflow.agent.toolset import ToolSet
from bumaren_agent_workflow.tools.schema import ToolSchema


class _BackgroundLoop:
    """常驻后台线程里的一个 asyncio event loop,供同步代码提交协程执行。

    单纯的一次性协程(如 list_tools/call_tool)用 run() 提交即可。但
    stdio_client/ClientSession 这类基于 anyio TaskGroup 的异步上下文管理器,
    进入(__aenter__)和退出(__aexit__)必须发生在同一个 asyncio Task 里,
    否则 anyio 会报 "Attempted to exit cancel scope in a different task than
    it was entered in"——run_coroutine_threadsafe 每次调用都会新开一个 Task,
    不满足这个要求。因此连接的建立/关闭改由 run_session() 提交一个长期挂起
    的协程,把 __aenter__/等待关闭信号/__aexit__ 全部串在同一个 Task 内完成。
    """

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def run(self, coro: Any) -> Any:
        """把一次性协程提交到后台 loop 执行,阻塞当前线程直到拿到结果或异常。"""
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()

    def submit(self, coro: Any) -> "concurrent.futures.Future[Any]":
        """提交一个协程但不等待,返回 concurrent.futures.Future 供调用方自行等待。"""
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def call_soon(self, callback: Callable[[], Any]) -> None:
        self._loop.call_soon_threadsafe(callback)

    def stop(self) -> None:
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)
        self._loop.close()


class MCPServer:
    """一个 MCP Server 连接:负责握手、列出工具、转发工具调用,并能打包成 ToolSet。

    Attributes:
        name: 该 Server 的标识,直接作为打包出的 ToolSet.name。
    """

    def __init__(self, name: str, params: StdioServerParameters) -> None:
        self.name = name
        self._params = params
        self._loop: _BackgroundLoop | None = None
        self._session: ClientSession | None = None
        self._close_event: asyncio.Event | None = None
        self._session_task: "concurrent.futures.Future[Any]" | None = None

    @classmethod
    def stdio(
        cls,
        name: str,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> "MCPServer":
        """构造一个通过 stdio 拉起子进程的 MCP Server(如 `npx @playwright/mcp`)。

        Args:
            name: 该 Server 的标识,打包出的 ToolSet 会用这个名字。
            command: 启动子进程的可执行文件,如 "npx"。
            args: 命令行参数,如 ["@playwright/mcp@latest"]。
            env: 传给子进程的额外环境变量;为 None 时子进程不继承任何变量
                (行为对齐 StdioServerParameters 默认值,如需继承当前环境
                请显式传入 os.environ 的拷贝)。
            cwd: 子进程工作目录。

        实际的子进程 spawn 与 MCP initialize 握手发生在 connect() 里,这里
        只记录参数,不产生任何 I/O。
        """
        params = StdioServerParameters(command=command, args=args or [], env=env, cwd=cwd)
        return cls(name, params)

    def connect(self) -> "MCPServer":
        """建立连接:拉起子进程、完成 MCP initialize 握手。重复调用是安全的(幂等)。

        子进程连接的 __aenter__/__aexit__ 必须配对发生在同一个 asyncio Task
        里(见 _BackgroundLoop 的说明),所以这里把"建立连接 -> 挂起等待关闭信号
        -> 退出连接"整段提交成后台 loop 上的*一个*长期运行的协程(_serve),
        用一个 concurrent.futures.Future 把里面 initialize 完成后的 session
        对象带回调用方这一侧,阻塞等待直到握手完成或失败。
        """
        if self._session is not None:
            return self
        self._loop = _BackgroundLoop()
        ready: "concurrent.futures.Future[ClientSession]" = concurrent.futures.Future()
        self._session_task = self._loop.submit(self._serve(ready))
        try:
            self._session = ready.result()
        except BaseException:
            self._loop.stop()
            self._loop = None
            self._session_task = None
            raise
        return self

    async def _serve(self, ready: "concurrent.futures.Future[ClientSession]") -> None:
        """在后台 loop 的同一个 Task 里完成:连接 -> 交出 session -> 等待关闭 -> 断开连接。"""
        close_event = asyncio.Event()
        self._close_event = close_event
        try:
            async with stdio_client(self._params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    ready.set_result(session)
                    await close_event.wait()
        except BaseException as exc:
            if not ready.done():
                ready.set_exception(exc)
            else:
                raise

    def close(self) -> None:
        """关闭连接:通知 _serve 退出连接、终止子进程、停掉后台 loop。重复调用是安全的。"""
        if self._session is None:
            return
        loop, close_event, session_task = self._loop, self._close_event, self._session_task
        self._session = None
        self._loop = None
        self._close_event = None
        self._session_task = None
        assert loop is not None and close_event is not None and session_task is not None
        try:
            loop.call_soon(close_event.set)
            session_task.result(timeout=10)
        finally:
            loop.stop()

    def __enter__(self) -> "MCPServer":
        return self.connect()

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def list_tools(self) -> list[ToolSchema]:
        """列出该 MCP Server 暴露的所有工具,转换成框架的 ToolSchema。

        MCP 的 Tool.inputSchema 本身就是 JSON Schema,与 ToolSchema.parameters
        的形态一致,直接透传,不需要像 schema_from_func 那样从函数签名反推。
        """
        session, loop = self._require_connected()
        result = loop.run(session.list_tools())
        return [_to_tool_schema(t) for t in result.tools]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        """同步调用一个远程 MCP 工具,返回拼接后的文本结果。

        若 MCP Server 以 isError=True 回传(工具执行失败,而非协议/传输层
        错误),这里转成一次普通异常抛出——与 ToolExecutor.execute() 对本地
        @tool 函数异常的处理方式完全一致:异常文本会被回填成 role="tool" 消息
        内容,交给模型自行判断是否重试/纠正入参,而不会让整个 agentic loop 崩溃。
        """
        session, loop = self._require_connected()
        result: CallToolResult = loop.run(session.call_tool(name, arguments))
        text = _format_content(result.content)
        if result.isError:
            raise RuntimeError(text or f"MCP 工具 {name!r} 调用失败(isError=True),未提供错误文本")
        return text

    def toolset(self) -> ToolSet:
        """把该 MCP Server 当前暴露的全部工具打包成一个 ToolSet。

        每个远程工具对应一个同步包装函数,调用时把关键字参数原样转发给
        call_tool——不在本地重复校验入参,交由 MCP Server 端按其 inputSchema
        校验,校验失败时通过 isError 回传,和其他运行期错误走同一条路径。
        """
        schemas = self.list_tools()
        tools = [(self._make_wrapper(schema.name), schema) for schema in schemas]
        return ToolSet(name=self.name, tools=tools)

    def _make_wrapper(self, tool_name: str) -> Callable[..., str]:
        def _call(**kwargs: Any) -> str:
            return self.call_tool(tool_name, kwargs)

        _call.__name__ = tool_name
        return _call

    def _require_connected(self) -> tuple[ClientSession, _BackgroundLoop]:
        if self._session is None or self._loop is None:
            raise RuntimeError(f"MCPServer({self.name!r}) 尚未连接,请先调用 connect() 或用 with 语句")
        return self._session, self._loop


def _to_tool_schema(t: Tool) -> ToolSchema:
    return ToolSchema(
        name=t.name,
        description=t.description or "",
        parameters=t.inputSchema or {"type": "object", "properties": {}},
    )


def _format_content(blocks: list[Any]) -> str:
    """把 CallToolResult.content(文本/图片/嵌入资源等内容块列表)拼成一段文本。

    文本块直接取 text;非文本块(如 Playwright 截图产生的 ImageContent)
    目前没有可回填给纯文本 LLM 消息的形态,退化为该块的 JSON 摘要,至少让
    模型知道"这里返回了一个 xxx 类型的内容"而不是静默丢弃。
    """
    parts = []
    for block in blocks:
        if isinstance(block, TextContent):
            parts.append(block.text)
        else:
            parts.append(json.dumps(block.model_dump(mode="json"), ensure_ascii=False))
    return "\n".join(parts)
