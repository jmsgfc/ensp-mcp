"""Stable output artifact exports for MCP, board and debugging workflows."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_OUTPUT_DIR = _PROJECT_ROOT / "output"


def ensure_output_dir() -> Path:
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return _OUTPUT_DIR


def export_json_artifact(filename: str, payload: Any) -> str:
    output_dir = ensure_output_dir()
    target = output_dir / filename
    body = {
        "generated_at": datetime.now().isoformat(),
        "data": payload,
    }
    target.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(target.resolve())


def export_markdown_artifact(filename: str, content: str) -> str:
    output_dir = ensure_output_dir()
    target = output_dir / filename
    target.write_text(content, encoding="utf-8")
    return str(target.resolve())


def read_artifact(filename: str) -> dict[str, Any]:
    target = ensure_output_dir() / filename
    if not target.exists():
        return {
            "success": False,
            "error": f"输出文件不存在: {target}",
            "path": str(target.resolve()),
        }

    if target.suffix.lower() == ".json":
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return {
                "success": False,
                "error": f"JSON 解析失败: {exc}",
                "path": str(target.resolve()),
            }
        return {"success": True, "path": str(target.resolve()), "format": "json", "content": payload}

    return {
        "success": True,
        "path": str(target.resolve()),
        "format": "markdown" if target.suffix.lower() == ".md" else "text",
        "content": target.read_text(encoding="utf-8"),
    }
