"""Command whitelist validation helpers."""

import re
from pathlib import Path
from typing import Optional

import yaml

from backend.adapters.base_adapter import CommandRejectedError

_whitelist_config: Optional[dict] = None
_whitelist_path: Optional[Path] = None


def _get_whitelist_path() -> Path:
    global _whitelist_path
    if _whitelist_path is None:
        root = Path(__file__).resolve().parent.parent.parent
        _whitelist_path = root / "config" / "command_whitelist.yaml"
    return _whitelist_path


def _load_whitelist() -> dict:
    global _whitelist_config
    if _whitelist_config is None:
        path = _get_whitelist_path()
        if not path.exists():
            raise FileNotFoundError(f"白名单配置文件不存在: {path}")
        with open(path, "r", encoding="utf-8") as f:
            _whitelist_config = yaml.safe_load(f)
    return _whitelist_config


def reload_whitelist() -> dict:
    global _whitelist_config
    _whitelist_config = None
    return _load_whitelist()


def normalize_command(command: str) -> str:
    if not command:
        return ""
    cmd = command.strip()
    cmd = re.sub(r"\s+", " ", cmd)
    return cmd.lower()


def _has_command_separator(command: str) -> bool:
    return bool(re.search(r"[;|&]", command))


def validate_command(command: str) -> tuple[bool, Optional[str]]:
    config = _load_whitelist()
    normalized = normalize_command(command)

    if not normalized:
        return False, "空命令"

    if _has_command_separator(command):
        return False, "命令包含非法拼接符"

    blocked_commands = config.get("blocked_commands", [])
    for blocked in blocked_commands:
        blocked_lower = blocked.lower()
        if normalized == blocked_lower or normalized.startswith(blocked_lower + " "):
            return False, f"危险命令已被阻断: {blocked}"

    allowed_prefixes = config.get("allowed_prefixes", [])
    has_allowed_prefix = any(
        normalized.startswith(prefix.lower() + " ") or normalized == prefix.lower()
        for prefix in allowed_prefixes
    )
    if not has_allowed_prefix:
        first_token = normalized.split()[0] if normalized else "(空)"
        return False, f"命令不在允许的前缀范围内: {first_token}"

    allowed_commands = config.get("allowed_commands", [])
    for allowed in allowed_commands:
        if normalized == allowed.lower():
            return True, None

    command_patterns = config.get("command_patterns", [])
    for pattern in command_patterns:
        if re.fullmatch(pattern, normalized):
            return True, None

    return False, f"命令不在精确白名单中: {normalized}"


def check_command(command: str) -> str:
    normalized = normalize_command(command)
    is_valid, reason = validate_command(command)
    if not is_valid:
        raise CommandRejectedError(command=command, reason=reason)
    return normalized
