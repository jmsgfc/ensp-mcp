"""Runtime topology path resolution for the eNSP MCP.

Topology selection is intentionally strict:
- TOPOLOGY_FILE may point to an absolute path.
- A relative TOPOLOGY_FILE is resolved from the current caller directory.
- Without TOPOLOGY_FILE, only the current caller directory is searched.

The current caller directory is resolved in this order:
1. ENSP_MCP_CALLER_CWD
2. The MCP process current working directory

There is no built-in fallback topology. Results from any other directory must
be treated as unavailable for the current request.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DEVICES = _PROJECT_ROOT / "config" / "devices.yaml"


def _get_current_directory() -> Path:
    caller_cwd = os.getenv("ENSP_MCP_CALLER_CWD")
    if caller_cwd:
        return Path(caller_cwd).expanduser().resolve()
    return Path.cwd().resolve()


def _resolve_current_relative(path_value: str) -> Path:
    path = Path(path_value).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (_get_current_directory() / path).resolve()


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

    current_dir = _get_current_directory()
    named_topo = current_dir / f"{current_dir.name}.topo"
    if named_topo.exists():
        return named_topo.resolve()

    topo_files = sorted(current_dir.glob("*.topo"))
    if len(topo_files) == 1:
        return topo_files[0].resolve()
    if len(topo_files) > 1:
        names = ", ".join(path.name for path in topo_files)
        raise RuntimeError(
            f"当前目录存在多个 .topo 文件，请设置 TOPOLOGY_FILE 明确指定: {current_dir}: {names}"
        )

    raise FileNotFoundError(
        f"当前目录没有 .topo 文件: {current_dir}。请在当前目录放置 .topo 文件，或设置 TOPOLOGY_FILE 指向当前拓扑。"
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


def _candidate_search_roots(search_dir: str | None = None) -> list[tuple[str, Path]]:
    roots: list[tuple[str, Path]] = []
    seen: set[Path] = set()

    def add_root(label: str, path: Path | None) -> None:
        if path is None:
            return
        resolved = path.expanduser().resolve()
        if not resolved.exists() or not resolved.is_dir() or resolved in seen:
            return
        seen.add(resolved)
        roots.append((label, resolved))

    if search_dir:
        add_root("search_dir", Path(search_dir))
        return roots

    add_root("caller_cwd", Path(os.getenv("ENSP_MCP_CALLER_CWD", "")) if os.getenv("ENSP_MCP_CALLER_CWD") else None)
    add_root("process_cwd", Path.cwd())

    home = Path.home()
    add_root("desktop", home / "Desktop")
    add_root("documents", home / "Documents")
    add_root("downloads", home / "Downloads")

    return roots


def find_topology_files(
    search_dir: str | None = None,
    *,
    max_results: int = 20,
) -> dict[str, Any]:
    """Find candidate .topo files for the user to choose from."""

    if max_results < 1:
        raise ValueError("max_results 必须大于等于 1")

    roots = _candidate_search_roots(search_dir)
    active_topology: Path | None
    try:
        active_topology = get_topology_path().resolve()
    except (FileNotFoundError, RuntimeError):
        active_topology = None

    candidates: list[dict[str, Any]] = []
    seen_files: set[Path] = set()

    for source, root in roots:
        for topo_path in root.rglob("*.topo"):
            resolved = topo_path.resolve()
            if resolved in seen_files:
                continue
            seen_files.add(resolved)
            stat = resolved.stat()
            candidates.append({
                "path": str(resolved),
                "name": resolved.name,
                "directory": str(resolved.parent),
                "source": source,
                "modified_at": stat.st_mtime,
                "is_named_after_directory": resolved.stem == resolved.parent.name,
                "is_active": active_topology == resolved,
            })

    candidates.sort(
        key=lambda item: (
            not item["is_active"],
            not item["is_named_after_directory"],
            -item["modified_at"],
            item["path"].lower(),
        )
    )
    limited = candidates[:max_results]
    for item in limited:
        item["modified_at"] = int(item["modified_at"])

    return {
        "success": True,
        "search_dir": str(Path(search_dir).expanduser().resolve()) if search_dir else None,
        "roots": [{"source": source, "path": str(path)} for source, path in roots],
        "count": len(limited),
        "truncated": len(candidates) > len(limited),
        "active_topology": str(active_topology) if active_topology is not None else None,
        "candidates": limited,
    }
