"""Runtime topology path resolution for the eNSP MCP.

Topology selection is intentionally dynamic:
- TOPOLOGY_FILE may point to an absolute path.
- A relative TOPOLOGY_FILE is resolved from the current working directory.
- Without TOPOLOGY_FILE, the current working directory must contain the lab
  topology: first <cwd-name>.topo, otherwise exactly one *.topo file.

There is no built-in fallback topology. If no current lab topology can be
found, callers should return a clear tool-level error.
"""

from __future__ import annotations

import os
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DEVICES = _PROJECT_ROOT / "config" / "devices.yaml"


def _resolve_current_relative(path_value: str) -> Path:
    path = Path(path_value).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (Path.cwd() / path).resolve()


def get_topology_path() -> Path:
    """Return the active .topo path for this invocation.

    The function never reuses a previously discovered file and never falls back
    to a project-bundled topology.
    """

    env_path = os.getenv("TOPOLOGY_FILE")
    if env_path:
        path = _resolve_current_relative(env_path)
        if not path.exists():
            raise FileNotFoundError(
                f"TOPOLOGY_FILE 指定的拓扑文件不存在: {path}"
            )
        if path.suffix.lower() != ".topo":
            raise RuntimeError(f"TOPOLOGY_FILE 必须指向 .topo 文件: {path}")
        return path

    cwd = Path.cwd().resolve()
    named_topo = cwd / f"{cwd.name}.topo"
    if named_topo.exists():
        return named_topo.resolve()

    topo_files = sorted(cwd.glob("*.topo"))
    if len(topo_files) == 1:
        return topo_files[0].resolve()
    if len(topo_files) > 1:
        names = ", ".join(path.name for path in topo_files)
        raise RuntimeError(
            "当前目录存在多个 .topo 文件，请设置 TOPOLOGY_FILE 明确指定: "
            f"{names}"
        )

    raise FileNotFoundError(
        f"当前目录没有 .topo 文件: {cwd}。请进入实验目录或设置 TOPOLOGY_FILE。"
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
