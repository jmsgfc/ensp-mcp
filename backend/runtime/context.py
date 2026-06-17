"""共享运行时上下文。

让 API 层（main.py）和 MCP 层（mcp/tools.py）复用同一套
DeviceService / LogService 实例，避免状态分裂。

使用方式：
    from backend.runtime.context import get_device_service, get_log_service

    device_service = get_device_service()
    log_service = get_log_service()
"""

from __future__ import annotations

from typing import Optional

from backend.services.device_service import DeviceService
from backend.services.log_service import LogService


class RuntimeContext:
    """持有进程级共享的 service 实例。"""

    def __init__(self) -> None:
        self._log_service: Optional[LogService] = None
        self._device_service: Optional[DeviceService] = None

    @property
    def log_service(self) -> LogService:
        if self._log_service is None:
            self._log_service = LogService()
        return self._log_service

    @property
    def device_service(self) -> DeviceService:
        if self._device_service is None:
            self._device_service = DeviceService(log_service=self.log_service)
        return self._device_service

    def reset(self) -> None:
        """重置为初始状态（用于测试隔离）。"""
        self._log_service = None
        self._device_service = None


# --- 模块级单例 ---

_ctx: Optional[RuntimeContext] = None


def get_context() -> RuntimeContext:
    """获取全局 RuntimeContext 单例。"""
    global _ctx
    if _ctx is None:
        _ctx = RuntimeContext()
    return _ctx


def get_device_service() -> DeviceService:
    """获取全局 DeviceService 单例。"""
    return get_context().device_service


def get_log_service() -> LogService:
    """获取全局 LogService 单例。"""
    return get_context().log_service


def reset_context() -> None:
    """重置全局上下文（用于测试隔离）。"""
    global _ctx
    if _ctx is not None:
        _ctx.reset()
    _ctx = None
