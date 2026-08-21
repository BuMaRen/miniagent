import sys
import unittest
from pathlib import Path

try:
    from bumaren_agent_workflow.tools.mcp import MCPServer

    _IMPORT_ERROR = None
except ImportError as e:  # pragma: no cover - depends on optional dependency
    _IMPORT_ERROR = e

from bumaren_agent_workflow.tools.registry import ToolRegistry

_FIXTURE = Path(__file__).parent / "_mcp_fixture_server.py"


def _fixture_server() -> "MCPServer":
    return MCPServer.stdio("fixture", command=sys.executable, args=[str(_FIXTURE)])


@unittest.skipIf(_IMPORT_ERROR is not None, f"mcp package not installed: {_IMPORT_ERROR}")
class MCPServerTests(unittest.TestCase):
    def test_list_tools_returns_schemas_from_remote_server(self):
        server = _fixture_server().connect()
        try:
            schemas = server.list_tools()
        finally:
            server.close()

        names = {s.name for s in schemas}
        self.assertEqual(names, {"add", "boom"})
        add_schema = next(s for s in schemas if s.name == "add")
        self.assertEqual(set(add_schema.parameters["required"]), {"a", "b"})

    def test_toolset_wraps_remote_tool_as_callable(self):
        server = _fixture_server().connect()
        try:
            toolset = server.toolset()
            add_func = next(f for f, s in toolset.tools if s.name == "add")
            result = add_func(a=2, b=3)
        finally:
            server.close()

        self.assertEqual(result, "5")

    def test_call_tool_error_raises_runtime_error(self):
        server = _fixture_server().connect()
        try:
            with self.assertRaises(RuntimeError) as cm:
                server.call_tool("boom", {})
        finally:
            server.close()

        self.assertIn("boom", str(cm.exception))

    def test_context_manager_connects_and_closes(self):
        server = _fixture_server()
        with server as opened:
            self.assertIs(opened, server)
            schemas = server.list_tools()
        self.assertEqual({s.name for s in schemas}, {"add", "boom"})
        # 退出 with 块后连接应已关闭,再次调用要能明确报错而不是挂起/崩溃。
        with self.assertRaises(RuntimeError):
            server.list_tools()

    def test_operations_before_connect_raise_runtime_error(self):
        server = _fixture_server()
        with self.assertRaises(RuntimeError):
            server.list_tools()

    def test_toolset_registers_into_tool_registry_like_a_local_toolset(self):
        # 验证适配层产出的 ToolSet 能直接走 agent.load_toolset() 同一条路径:
        # 把 (func, schema) 注册进 ToolRegistry,和本地 @tool 函数一视同仁。
        registry = ToolRegistry()
        server = _fixture_server().connect()
        try:
            toolset = server.toolset()
            for func, schema in toolset.tools:
                self.assertTrue(registry.register(schema.name, func, schema))
            result = registry.get("add")(a=10, b=32)
        finally:
            server.close()

        self.assertEqual(result, "42")


if __name__ == "__main__":
    unittest.main()
