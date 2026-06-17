"""日志服务模块。

职责：
1. 记录设备查询操作
2. 记录命令执行与安全拒绝
3. 提供日志查询接口

日志存储在内存中，以列表形式保留，不依赖外部日志框架。
后续可扩展为文件持久化或结构化日志。
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class LogLevel(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    SECURITY = "security"


class LogAction(str, Enum):
    DEVICE_LIST = "device_list"
    DEVICE_STATUS = "device_status"
    COMMAND_EXEC = "command_exec"
    COMMAND_REJECTED = "command_rejected"
    CONFIG_BACKUP = "config_backup"
    CONNECTION_ERROR = "connection_error"
    CONFIG_PREVIEW = "config_preview"
    CONFIG_DEPLOY = "config_deploy"
    CONFIG_SAVE = "config_save"
    CONFIG_ROLLBACK = "config_rollback"


@dataclass
class LogEntry:
    """单条日志记录。"""
    id: int
    timestamp: str
    level: LogLevel
    action: LogAction
    device_id: Optional[str]
    device_name: Optional[str]
    command: Optional[str]
    detail: str
    success: bool = True


class LogService:
    """内存日志服务。

    当前阶段使用内存存储，支持按时间倒序查询。
    不引入外部日志依赖，保持最小化。
    """

    def __init__(self, max_entries: int = 1000):
        self._entries: list[LogEntry] = []
        self._next_id = 1
        self._max_entries = max_entries

    def _add(
        self,
        level: LogLevel,
        action: LogAction,
        detail: str,
        device_id: Optional[str] = None,
        device_name: Optional[str] = None,
        command: Optional[str] = None,
        success: bool = True,
    ) -> LogEntry:
        """内部添加日志条目。"""
        entry = LogEntry(
            id=self._next_id,
            timestamp=datetime.now().isoformat(),
            level=level,
            action=action,
            device_id=device_id,
            device_name=device_name,
            command=command,
            detail=detail,
            success=success,
        )
        self._next_id += 1

        self._entries.append(entry)

        # 超出容量时丢弃最旧的日志
        if len(self._entries) > self._max_entries:
            self._entries = self._entries[-self._max_entries:]

        return entry

    def log_device_list(self, count: int) -> LogEntry:
        """记录设备列表查询。"""
        return self._add(
            level=LogLevel.INFO,
            action=LogAction.DEVICE_LIST,
            detail=f"查询设备列表，返回 {count} 台设备",
        )

    def log_device_status(self, device_id: str, device_name: str, success: bool, detail: str) -> LogEntry:
        """记录设备状态查询。"""
        return self._add(
            level=LogLevel.INFO if success else LogLevel.ERROR,
            action=LogAction.DEVICE_STATUS,
            device_id=device_id,
            device_name=device_name,
            detail=detail,
            success=success,
        )

    def log_command_exec(
        self,
        device_id: str,
        device_name: str,
        command: str,
        success: bool,
        detail: str,
    ) -> LogEntry:
        """记录命令执行结果。"""
        return self._add(
            level=LogLevel.INFO if success else LogLevel.ERROR,
            action=LogAction.COMMAND_EXEC,
            device_id=device_id,
            device_name=device_name,
            command=command,
            detail=detail,
            success=success,
        )

    def log_command_rejected(self, command: str, reason: str) -> LogEntry:
        """记录命令被安全层拒绝。"""
        return self._add(
            level=LogLevel.SECURITY,
            action=LogAction.COMMAND_REJECTED,
            command=command,
            detail=f"命令被拒绝: {reason}",
            success=False,
        )

    def log_config_backup(
        self, device_id: str, device_name: str, success: bool, detail: str
    ) -> LogEntry:
        """记录配置备份操作。"""
        return self._add(
            level=LogLevel.INFO if success else LogLevel.ERROR,
            action=LogAction.CONFIG_BACKUP,
            device_id=device_id,
            device_name=device_name,
            detail=detail,
            success=success,
        )

    def log_connection_error(self, device_id: str, device_name: str, reason: str) -> LogEntry:
        """记录连接错误。"""
        return self._add(
            level=LogLevel.ERROR,
            action=LogAction.CONNECTION_ERROR,
            device_id=device_id,
            device_name=device_name,
            detail=f"连接失败: {reason}",
            success=False,
        )

    def log_config_preview(self, draft_id: str, device_count: int) -> LogEntry:
        """记录配置预览操作。"""
        return self._add(
            level=LogLevel.INFO,
            action=LogAction.CONFIG_PREVIEW,
            detail=f"生成配置草案 {draft_id}，涉及 {device_count} 台设备",
        )

    def log_config_deploy(
        self, draft_id: str, success: bool, detail: str
    ) -> LogEntry:
        """记录配置下发操作。"""
        return self._add(
            level=LogLevel.INFO if success else LogLevel.ERROR,
            action=LogAction.CONFIG_DEPLOY,
            detail=f"[{draft_id}] {detail}",
            success=success,
        )

    def log_config_save(
        self, device_id: str, device_name: str, success: bool, detail: str
    ) -> LogEntry:
        """记录配置保存操作。"""
        return self._add(
            level=LogLevel.INFO if success else LogLevel.ERROR,
            action=LogAction.CONFIG_SAVE,
            device_id=device_id,
            device_name=device_name,
            detail=detail,
            success=success,
        )

    def log_config_rollback(
        self, detail: str, success: bool,
        device_id: Optional[str] = None,
        device_name: Optional[str] = None,
    ) -> LogEntry:
        """记录配置回滚操作。"""
        return self._add(
            level=LogLevel.INFO if success else LogLevel.ERROR,
            action=LogAction.CONFIG_ROLLBACK,
            device_id=device_id,
            device_name=device_name,
            detail=detail,
            success=success,
        )

    def get_logs(
        self,
        limit: int = 100,
        level: Optional[LogLevel] = None,
        action: Optional[LogAction] = None,
        device_id: Optional[str] = None,
    ) -> list[LogEntry]:
        """查询日志，按时间倒序返回。"""
        entries = self._entries

        if level:
            entries = [e for e in entries if e.level == level]
        if action:
            entries = [e for e in entries if e.action == action]
        if device_id:
            entries = [e for e in entries if e.device_id == device_id]

        # 按时间倒序
        entries = sorted(entries, key=lambda e: e.timestamp, reverse=True)

        return entries[:limit]

    def get_log_count(self) -> int:
        """返回当前日志总数。"""
        return len(self._entries)

    def clear(self) -> None:
        """清空内存日志，主要用于测试隔离。"""
        self._entries.clear()
        self._next_id = 1
