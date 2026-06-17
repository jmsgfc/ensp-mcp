"""MCP 工具层。

将后端查询能力封装为 MCP 工具，供大模型通过统一入口调用。

当前阶段仅暴露只读工具，不开放 deploy/save/rollback。
"""

from backend.mcp.tools import TOOL_REGISTRY, call_tool, list_tools

__all__ = ["TOOL_REGISTRY", "call_tool", "list_tools"]
