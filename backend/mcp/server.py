"""MCP Server 暴露层。

默认将 backend.mcp.tools 中的精简工具通过 MCP 协议（stdio）暴露，
供外部 MCP 客户端（如 Claude Desktop、Cursor 等）调用。

职责：
1. 复用 backend.mcp.tools 的工具注册表和工具 profile
2. 适配 MCP SDK 的 Server 接口
3. 不重复实现业务逻辑
4. 不绕过现有安全边界

启动方式：
    python -m backend.mcp.server

MCP 客户端配置示例（Claude Desktop / Cursor）：
    {
      "mcpServers": {
        "ensp-mcp": {
          "command": "python",
          "args": ["-m", "backend.mcp.server"],
          "cwd": "/path/to/current-lab"
        }
      }
    }

默认工具 profile 为 compact。需要调试细粒度工具时，可设置：
    ENSP_MCP_TOOL_PROFILE=legacy
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from backend.mcp.tools import list_tools as _list_tools, call_tool as _call_tool

logger = logging.getLogger(__name__)

# --- MCP Server 实例 ---

server = Server("ensp-mcp")


# --- 工具列表 ---

@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    """返回所有已注册的 MCP 工具定义。"""
    tools = _list_tools()
    return [
        Tool(
            name=t["name"],
            description=t["description"],
            inputSchema=t["input_schema"],
        )
        for t in tools
    ]


# --- 工具调用 ---

@server.call_tool()
async def handle_call_tool(
    name: str, arguments: dict[str, Any] | None
) -> list[TextContent]:
    """调用指定的 MCP 工具，返回结构化结果。"""
    result = _call_tool(name, arguments)
    return [
        TextContent(
            type="text",
            text=json.dumps(result, ensure_ascii=False, indent=2),
        )
    ]


# --- 入口 ---

async def _run_server() -> None:
    """启动 MCP stdio server。"""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main() -> None:
    """同步入口。"""
    asyncio.run(_run_server())


if __name__ == "__main__":
    main()
