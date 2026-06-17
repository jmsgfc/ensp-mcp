"""设备适配器基类定义。

所有设备适配器必须实现此接口，确保查询层与传输层解耦。
当前阶段只允许只读操作；配置下发能力留待后续阶段。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class DeviceInfo:
    """设备基础信息模型。"""
    id: str
    name: str
    type: str
    vendor: str
    model: str
    host: Optional[str] = None
    port: Optional[int] = None
    protocol: Optional[str] = None


@dataclass
class DeviceStatus:
    """设备运行状态模型。"""
    device_id: str
    device_name: str
    is_online: bool
    uptime: Optional[str] = None
    cpu_usage: Optional[str] = None
    memory_usage: Optional[str] = None
    version: Optional[str] = None
    checked_at: Optional[str] = None


@dataclass
class CommandResult:
    """命令执行结果模型。"""
    device_id: str
    device_name: str
    command: str
    normalized_command: str
    success: bool
    output: str
    error: Optional[str] = None
    executed_at: Optional[str] = None


@dataclass
class BackupResult:
    """配置备份结果模型。"""
    device_id: str
    device_name: str
    success: bool
    backup_path: Optional[str] = None
    error: Optional[str] = None
    backed_up_at: Optional[str] = None


@dataclass
class CommandOutput:
    """单条命令的诊断输出。"""
    command: str
    success: bool
    output: Optional[str] = None
    error: Optional[str] = None


@dataclass
class DeviceDiagnostics:
    """单台设备的聚合诊断数据。"""
    device_id: str
    device_name: str
    collected_at: str
    commands: list[CommandOutput]


@dataclass
class ConfigCommandResult:
    """单条配置命令的执行结果。"""
    command: str
    success: bool
    output: Optional[str] = None
    error: Optional[str] = None


@dataclass
class SaveResult:
    """配置保存结果模型。"""
    device_id: str
    device_name: str
    success: bool
    output: Optional[str] = None
    error: Optional[str] = None
    saved_at: Optional[str] = None


@dataclass
class RestoreResult:
    """配置恢复结果模型。"""
    device_id: str
    device_name: str
    success: bool
    output: Optional[str] = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    recovery_hint: Optional[str] = None
    manual_steps: Optional[list[str]] = None
    backup_path: Optional[str] = None
    restored_at: Optional[str] = None


@dataclass
class PcDhcpStatus:
    """PC 的 DHCP 地址获取状态。"""
    pc_name: str
    ip_address: Optional[str] = None
    mask: Optional[str] = None
    gateway: Optional[str] = None
    dhcp_state: int = 0  # 0=未获取, 1=已获取
    available: bool = True  # False 表示无法读取（如真实 eNSP）
    note: Optional[str] = None


class BaseAdapter(ABC):
    """设备适配器统一接口。

    职责：
    1. 列出可管理的设备
    2. 查询设备运行状态
    3. 执行只读命令
    4. 备份设备配置（只读导出，非下发）
    5. 执行受控配置命令（仅限内部生成的配置）

    约束：
    - run_show_command 经过白名单校验后再执行
    - run_config_commands 仅接受系统内部生成的命令列表
    """

    @abstractmethod
    def list_devices(self) -> list[DeviceInfo]:
        """返回当前适配器管理的设备列表。"""
        ...

    @abstractmethod
    def get_device_status(self, device_id: str) -> DeviceStatus:
        """查询指定设备的运行状态。

        Args:
            device_id: 设备唯一标识

        Raises:
            DeviceNotFoundError: 设备不存在
            ConnectionError: 设备不可达
        """
        ...

    @abstractmethod
    def run_show_command(self, device_id: str, command: str) -> CommandResult:
        """在指定设备上执行一条只读命令。

        调用方必须在调用前完成白名单校验；适配器层可做二次防线。

        Args:
            device_id: 设备唯一标识
            command: 已通过白名单校验的命令

        Raises:
            DeviceNotFoundError: 设备不存在
            CommandRejectedError: 命令被安全层拒绝
            ConnectionError: 设备不可达
        """
        ...

    @abstractmethod
    def backup_config(self, device_id: str) -> BackupResult:
        """备份指定设备的当前配置（只读导出）。

        Args:
            device_id: 设备唯一标识

        Raises:
            DeviceNotFoundError: 设备不存在
            ConnectionError: 设备不可达
        """
        ...

    def get_device_diagnostics(self, device_id: str) -> DeviceDiagnostics:
        """获取单台设备的聚合诊断数据。

        执行多条只读诊断命令，返回聚合结果。
        单条命令失败不中断整体诊断，错误记录在 CommandOutput.error 中。

        Args:
            device_id: 设备唯一标识

        Raises:
            DeviceNotFoundError: 设备不存在
            DeviceConnectionError: 设备完全不可达
        """
        raise NotImplementedError

    def run_config_commands(
        self, device_id: str, commands: list[str]
    ) -> list[ConfigCommandResult]:
        """在指定设备上执行一组配置命令。

        进入 system-view，逐条执行命令，退出 system-view。
        仅用于系统内部生成的受控配置，不暴露给用户自由输入。

        Args:
            device_id: 设备唯一标识
            commands: 系统内部生成的配置命令列表

        Raises:
            DeviceNotFoundError: 设备不存在
            DeviceConnectionError: 设备不可达
        """
        raise NotImplementedError

    def save_config(self, device_id: str) -> SaveResult:
        """保存设备当前配置到持久化存储（VRP save 命令）。

        Args:
            device_id: 设备唯一标识

        Raises:
            DeviceNotFoundError: 设备不存在
            DeviceConnectionError: 设备不可达
        """
        raise NotImplementedError

    def restore_config(self, device_id: str, backup_path: str) -> RestoreResult:
        """从备份文件恢复设备配置。

        仅用于回滚场景，不暴露通用配置恢复能力。
        当前阶段为保守实现，真实 eNSP 可能返回不支持。

        Args:
            device_id: 设备唯一标识
            backup_path: 备份文件路径

        Raises:
            DeviceNotFoundError: 设备不存在
            DeviceConnectionError: 设备不可达
        """
        raise NotImplementedError

    def get_pc_dhcp_status(self, pc_name: str) -> PcDhcpStatus:
        """获取 PC 的 DHCP 地址获取状态。

        当前阶段仅 Mock 适配器支持；真实 eNSP 的 PC 无 Telnet CLI，
        返回 available=False 并附带说明。

        Args:
            pc_name: PC 设备名称（如 "PC4"）

        Returns:
            PcDhcpStatus 实例
        """
        raise NotImplementedError(f"设备 {pc_name} 不支持 PC DHCP 状态查询")


class DeviceNotFoundError(Exception):
    """设备不存在异常。"""

    def __init__(self, device_id: str):
        self.device_id = device_id
        super().__init__(f"设备不存在: {device_id}")


class CommandRejectedError(Exception):
    """命令被安全层拒绝异常。"""

    def __init__(self, command: str, reason: str):
        self.command = command
        self.reason = reason
        super().__init__(f"命令被拒绝: {command}，原因: {reason}")


class DeviceConnectionError(Exception):
    """设备连接异常。"""

    def __init__(self, device_id: str, reason: str):
        self.device_id = device_id
        self.reason = reason
        super().__init__(f"设备连接失败: {device_id}，原因: {reason}")
