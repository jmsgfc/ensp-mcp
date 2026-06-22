"""Unified local launcher for the eNSP MCP project."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import uvicorn

from backend.topology.config import find_topology_files


def _build_launch_env(
    topology_file: str | None = None,
    workspace_dir: str | None = None,
    *,
    enable_real_ensp: bool = True,
) -> dict[str, str]:
    env = os.environ.copy()
    if topology_file:
        resolved_topology = Path(topology_file).expanduser().resolve()
        env["TOPOLOGY_FILE"] = str(resolved_topology)
        env["ENSP_MCP_CALLER_CWD"] = str(resolved_topology.parent)
    elif workspace_dir:
        env["ENSP_MCP_CALLER_CWD"] = str(Path(workspace_dir).expanduser().resolve())
    env["ENABLE_REAL_ENSP"] = "true" if enable_real_ensp else "false"
    return env


def _topology_start_hint(
    topology_file: str | None = None,
    workspace_dir: str | None = None,
) -> dict[str, Any]:
    search_dir = workspace_dir or (
        str(Path(topology_file).expanduser().resolve().parent) if topology_file else None
    )
    return find_topology_files(search_dir=search_dir, max_results=5)


def main() -> None:
    parser = argparse.ArgumentParser(description="eNSP-MCP 一键启动入口")
    parser.add_argument("--topology", help="可选，显式指定 .topo 文件")
    parser.add_argument("--workspace", help="可选，指定实验目录")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--with-mcp", action="store_true", help="同时在后台启动 MCP stdio 服务")
    args = parser.parse_args()

    env = _build_launch_env(args.topology, args.workspace, enable_real_ensp=True)
    hint = _topology_start_hint(args.topology, args.workspace)

    print("=== eNSP-MCP Launcher ===")
    if hint.get("active_topology"):
        print(f"Active topology: {hint['active_topology']}")
    elif hint.get("candidates"):
        print("No active topology resolved yet. Candidate .topo files:")
        for item in hint["candidates"]:
            print(f"  - {item['path']}")
    else:
        print("No .topo candidates found yet. You can still start the board and use find_topology_files.")
    print("Mode: real eNSP")

    if args.with_mcp:
        subprocess.Popen(
            [sys.executable, "-m", "backend.mcp.server"],
            cwd=str(Path(__file__).resolve().parents[1]),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print("Background MCP server started with current environment.")

    os.environ.update(env)
    print(f"Board URL: http://{args.host}:{args.port}/static/index.html")
    uvicorn.run("backend.main:app", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
