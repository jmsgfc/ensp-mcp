"""运行时上下文包。

提供 API 层与 MCP 层共享的 DeviceService / LogService 单例。
"""

from backend.runtime.context import get_context, get_device_service, get_log_service

__all__ = ["get_context", "get_device_service", "get_log_service"]
