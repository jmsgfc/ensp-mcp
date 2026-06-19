"""Runtime topology path resolution for the eNSP MCP.

Topology selection is intentionally dynamic:
- TOPOLOGY_FILE may point to an absolute path.
- A relative TOPOLOGY_FILE is resolved from the active lab workspace.
- Without TOPOLOGY_FILE, the active lab workspace must contain the topology:
  first <workspace-name>.topo, otherwise exactly one *.topo file.

The active lab workspace is resolved in this order:
1. ENSP_MCP_WORKSPACE_DIR
2. ENSP_MCP_CALLER_CWD
3. CODEX_WORKSPACE / WORKSPACE
4. The MCP process current working directory

There is no built-in fallback topology. If no current lab topology can be
found, callers should return a clear tool-level error.
"""

from __future__ import annotations

import os
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DEVICES = _PROJECT_ROOT / "config" / "devices.yaml"
_WORKSPACE_ENV_KEYS = (
    "ENSP_MCP_WORKSPACE_DIR",
    "ENSP_MCP_CALLER_CWD",
    "CODEX_WORKSPACE",
    "WORKSPACE",
)


def _resolve_current_relative(path_value: str) -> Path:
    path = Path(path_value).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (Path.cwd() / path).resolve()


def _candidate_workspace_dirs() -> list[Path]:
    candidates: list[Path] = []
    seen: set[str] = set()

    for key in _WORKSPACE_ENV_KEYS:
        value = os.getenv(key)
        if not value:
            continue
        resolved = Path(value).expanduser().resolve()
        marker = str(resolved)
        if marker not in seen:
            candidates.append(resolved)
            seen.add(marker)

    cwd = Path.cwd().resolve()
    cwd_marker = str(cwd)
    if cwd_marker not in seen:
        candidates.append(cwd)
    return candidates


def get_topology_path() -> Path:
    """Return the active .topo path for this invocation."""

    env_path = os.getenv("TOPOLOGY_FILE")
    if env_path:
        path = _resolve_current_relative(env_path)
        if not path.exists():
            raise FileNotFoundError(f"TOPOLOGY_FILE 指定的拓扑文件不存在: {path}")
        if path.suffix.lower() != ".topo":
            raise RuntimeError(f"TOPOLOGY_FILE 必须指向 .topo 文件: {path}")
        return path

    missing_dirs: list[Path] = []
    multi_topo_errors: list[str] = []

    for workspace_dir in _candidate_workspace_dirs():
        named_topo = workspace_dir / f"{workspace_dir.name}.topo"
        if named_topo.exists():
            return named_topo.resolve()

        topo_files = sorted(workspace_dir.glob("*.topo"))
        if len(topo_files) == 1:
            return topo_files[0].resolve()
        if len(topo_files) > 1:
            names = ", ".join(path.name for path in topo_files)
            multi_topo_errors.append(f"{workspace_dir}: {names}")
            continue
        missing_dirs.append(workspace_dir)

    if multi_topo_errors:
        raise RuntimeError(
            "以下目录存在多个 .topo 文件，请设置 TOPOLOGY_FILE 明确指定: "
            + " | ".join(multi_topo_errors)
        )

    searched = ", ".join(str(path) for path in missing_dirs) or str(Path.cwd().resolve())
    raise FileNotFoundError(
        f"未在候选工作目录中找到 .topo 文件: {searched}。请进入实验目录，或设置 TOPOLOGY_FILE / ENSP_MCP_WORKSPACE_DIR。"
    )


def get_topology_workspace_dir() -> Path:
    """Return the directory that owns the active topology."""

    return get_topology_path().resolve().parent


def get_devices_config_path() -> Path:
    """Return the devices.yaml path used for optional Telnet overrides."""

    env_path = os.getenv("DEVICES_FILE")
    if env_path:
        return _resolve_current_relative(env_path)

    try:
        sibling_devices = get_topology_workspace_dir() / "config" / "devices.yaml"
    except (FileNotFoundError, RuntimeError):
        return _DEFAULT_DEVICES

    if sibling_devices.exists():
        return sibling_devices.resolve()
    return _DEFAULT_DEVICES


def get_backups_dir() -> Path:
    """Return the directory used for deployment backups."""

    return _PROJECT_ROOT / "backups"
