"""tests/tools/test_mcp.py 用的独立 stdio MCP Server fixture。

作为子进程被 MCPServer.stdio(command=sys.executable, args=[__file__]) 拉起,
不属于测试用例本身,只是给 MCPServer 提供一个真实、最小的 MCP Server 对端。
"""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("test-fixture")


@mcp.tool()
def add(a: int, b: int) -> int:
    """两数相加。

    Args:
        a: 加数。
        b: 加数。
    """
    return a + b


@mcp.tool()
def boom() -> str:
    """总是失败,用于测试 MCPServer 对 isError 的处理。"""
    raise ValueError("boom")


if __name__ == "__main__":
    mcp.run(transport="stdio")
