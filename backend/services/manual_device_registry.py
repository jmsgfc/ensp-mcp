"""Manual device registry for non-topology workflows."""

from __future__ import annotations

import json
import socket
import uuid
from pathlib import Path
from typing import Any

from backend.adapters.telnet_client import TelnetClient, TelnetConfig, TelnetConnectionError


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_OUTPUT_DIR = _PROJECT_ROOT / "output"
_REGISTRY_PATH = _OUTPUT_DIR / "registered_devices.json"


def _ensure_output_dir() -> Path:
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return _OUTPUT_DIR


def _read_registry() -> list[dict[str, Any]]:
    if not _REGISTRY_PATH.exists():
        return []
    try:
        payload = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    devices = payload.get("devices", [])
    return devices if isinstance(devices, list) else []


def _write_registry(devices: list[dict[str, Any]]) -> None:
    _ensure_output_dir()
    payload = {"devices": devices}
    _REGISTRY_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def list_registered_devices() -> list[dict[str, Any]]:
    return _read_registry()


def has_registered_devices() -> bool:
    return bool(_read_registry())


def register_device(
    name: str,
    host: str,
    port: int,
    *,
    device_type: str = "router",
    vendor: str = "huawei",
    model: str = "manual",
    username_env: str | None = None,
    password_env: str | None = None,
) -> dict[str, Any]:
    devices = _read_registry()
    normalized_name = name.strip()
    if not normalized_name:
        raise ValueError("设备名称不能为空")
    if port < 1 or port > 65535:
        raise ValueError("端口号必须在 1-65535 之间")

    updated = False
    for item in devices:
        if item.get("name") == normalized_name:
            item.update({
                "host": host,
                "port": port,
                "type": device_type,
                "vendor": vendor,
                "model": model,
                "protocol": "telnet",
                "username_env": username_env,
                "password_env": password_env,
                "source": "manual",
            })
            updated = True
            record = item
            break
    else:
        record = {
            "id": f"manual-{uuid.uuid4()}",
            "name": normalized_name,
            "host": host,
            "port": port,
            "type": device_type,
            "vendor": vendor,
            "model": model,
            "protocol": "telnet",
            "username_env": username_env,
            "password_env": password_env,
            "source": "manual",
        }
        devices.append(record)

    _write_registry(devices)
    return {
        "success": True,
        "updated": updated,
        "device": record,
        "registry_path": str(_REGISTRY_PATH.resolve()),
    }


def unregister_device(name: str) -> dict[str, Any]:
    devices = _read_registry()
    remaining = [item for item in devices if item.get("name") != name]
    removed = len(remaining) != len(devices)
    _write_registry(remaining)
    return {
        "success": removed,
        "removed": removed,
        "name": name,
        "count": len(remaining),
        "registry_path": str(_REGISTRY_PATH.resolve()),
    }


def _probe_port(host: str, port: int, timeout: float = 0.5) -> bool:
    with socket.socket() as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((host, port)) == 0


def _discover_device_name(host: str, port: int) -> str | None:
    try:
        client = TelnetClient(TelnetConfig(host=host, port=port, timeout=2.0))
        client.connect()
        prompt = getattr(client, "_prompt", None)
        client.close()
    except TelnetConnectionError:
        return None

    if not prompt:
        return None
    return prompt.strip("<>[]#")


def auto_discover_devices(
    *,
    host: str = "127.0.0.1",
    start_port: int = 2000,
    end_port: int = 2050,
) -> dict[str, Any]:
    if start_port < 1 or end_port > 65535 or start_port > end_port:
        raise ValueError("端口范围无效")

    existing = {item.get("name"): item for item in _read_registry() if item.get("name")}
    discovered: list[dict[str, Any]] = []

    for port in range(start_port, end_port + 1):
        if not _probe_port(host, port):
            continue
        name = _discover_device_name(host, port) or f"device-{port}"
        record = {
            "id": existing.get(name, {}).get("id", f"manual-{uuid.uuid4()}"),
            "name": name,
            "host": host,
            "port": port,
            "type": existing.get(name, {}).get("type", "router"),
            "vendor": existing.get(name, {}).get("vendor", "huawei"),
            "model": existing.get(name, {}).get("model", "auto-discovered"),
            "protocol": "telnet",
            "username_env": existing.get(name, {}).get("username_env"),
            "password_env": existing.get(name, {}).get("password_env"),
            "source": "auto_discovered",
        }
        existing[name] = record
        discovered.append(record)

    merged = list(existing.values())
    merged.sort(key=lambda item: (str(item.get("host", "")), int(item.get("port", 0)), str(item.get("name", ""))))
    _write_registry(merged)
    return {
        "success": True,
        "host": host,
        "start_port": start_port,
        "end_port": end_port,
        "count": len(discovered),
        "devices": discovered,
        "registry_path": str(_REGISTRY_PATH.resolve()),
    }
