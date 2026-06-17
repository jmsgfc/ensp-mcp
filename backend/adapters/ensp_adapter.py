"""eNSP 设备适配器。

通过 Telnet 连接真实 eNSP 设备，执行只读查询命令。
当前阶段不支持配置下发。
"""

import os
from datetime import datetime
from typing import Optional

from backend.adapters.base_adapter import (
    BackupResult,
    BaseAdapter,
    CommandOutput,
    CommandResult,
    ConfigCommandResult,
    DeviceConnectionError,
    DeviceDiagnostics,
    DeviceInfo,
    DeviceNotFoundError,
    DeviceStatus,
    RestoreResult,
    SaveResult,
)
from backend.adapters.telnet_client import (
    TelnetClient,
    TelnetConfig,
    TelnetConnectionError,
    TelnetCommandError,
)
from backend.topology.config import get_backups_dir
from backend.utils.security import check_command


class ENSPAdapter(BaseAdapter):
    """eNSP 真实设备适配器。

    通过 Telnet 连接华为 VRP 设备，支持：
    - 设备状态查询
    - 只读命令执行
    - 配置备份（只读导出）

    不支持：
    - 配置下发
    - 命令白名单绕过
    """

    def __init__(self, devices_config: list[dict], enable_real: bool = False):
        self._devices_config = devices_config
        self._enable_real = enable_real
        self._device_map: dict[str, dict] = {
            d["id"]: d for d in devices_config
        }
        self._clients: dict[str, TelnetClient] = {}

    def _get_device_config(self, device_id: str) -> dict:
        """获取设备配置。"""
        config = self._device_map.get(device_id)
        if not config:
            raise DeviceNotFoundError(device_id)
        return config

    def _get_client(self, device_id: str, timeout: Optional[float] = None) -> TelnetClient:
        """获取或创建 Telnet 连接。"""
        if device_id in self._clients:
            client = self._clients[device_id]
            if client.connected:
                return client
            # 连接已断开，清理后重建
            del self._clients[device_id]

        config = self._get_device_config(device_id)

        if not config.get("host") or not config.get("port"):
            raise DeviceConnectionError(
                device_id=device_id,
                reason=f"设备 {config['name']} 无 Telnet 连接配置（host/port）",
            )

        # 从环境变量读取凭据
        username_env = config.get("username_env")
        password_env = config.get("password_env")
        username = os.environ.get(username_env, "") if username_env else ""
        password = os.environ.get(password_env, "") if password_env else ""

        telnet_config = TelnetConfig(
            host=config["host"],
            port=config["port"],
            username=username,
            password=password,
            timeout=timeout or 30.0,
        )

        client = TelnetClient(telnet_config)
        client.connect()
        self._clients[device_id] = client
        return client

    def _open_fresh_client(
        self, device_id: str, timeout: Optional[float] = None
    ) -> TelnetClient:
        """Open a new Telnet session for stateful operations."""
        self.disconnect(device_id)
        return self._get_client(device_id, timeout=timeout)

    def _prepare_user_view(self, client: TelnetClient) -> None:
        """Best-effort session prep before long reads or config writes."""
        try:
            client.send_command("screen-length 0 temporary")
        except (TelnetConnectionError, TelnetCommandError):
            pass

    def _build_backup_path(self, device_name: str) -> str:
        backup_dir = get_backups_dir()
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return str((backup_dir / f"{device_name}_{timestamp}.cfg").resolve())

    @staticmethod
    def _build_managed_config_commands(
        device_name: str,
        commands: list[str],
    ) -> list[str]:
        """Inject standard commands before task-specific config."""
        merged: list[str] = []
        seen: set[str] = set()
        for command in [
            f"sysname {device_name}",
            "undo info-center enable",
            *commands,
        ]:
            normalized = command.strip()
            if not normalized or normalized in seen:
                continue
            merged.append(normalized)
            seen.add(normalized)
        return merged

    def list_devices(self) -> list[DeviceInfo]:
        """返回设备列表。"""
        devices = []
        for cfg in self._devices_config:
            devices.append(DeviceInfo(
                id=cfg["id"],
                name=cfg["name"],
                type=cfg["type"],
                vendor=cfg["vendor"],
                model=cfg["model"],
                host=cfg.get("host"),
                port=cfg.get("port"),
                protocol=cfg.get("protocol"),
            ))
        return devices

    def get_device_status(self, device_id: str) -> DeviceStatus:
        """查询设备运行状态。"""
        config = self._get_device_config(device_id)

        # PC 类型不支持
        if config.get("type") == "pc":
            raise DeviceConnectionError(
                device_id=device_id,
                reason=f"设备类型 {config['type']} 不支持运行状态查询",
            )

        try:
            client = self._get_client(device_id)
            version_output = client.send_command("display version")
            uptime = _extract_uptime(version_output)
            version = _extract_version(version_output)
        except (TelnetConnectionError, TelnetCommandError) as e:
            raise DeviceConnectionError(
                device_id=device_id,
                reason=f"查询设备状态失败: {e}",
            ) from e

        return DeviceStatus(
            device_id=config["id"],
            device_name=config["name"],
            is_online=True,
            uptime=uptime,
            version=version,
            checked_at=datetime.now().isoformat(),
        )

    def run_show_command(self, device_id: str, command: str) -> CommandResult:
        """执行只读命令。"""
        normalized = check_command(command)
        config = self._get_device_config(device_id)

        # PC 类型不支持
        if config.get("type") == "pc":
            raise DeviceConnectionError(
                device_id=device_id,
                reason=f"设备类型 {config['type']} 不支持命令执行",
            )

        try:
            client = self._open_fresh_client(device_id, timeout=6.0)
            self._prepare_user_view(client)
            timeout = 20.0 if normalized == "display current-configuration" else 5.0
            output = client.send_command(normalized, timeout=timeout)
        except TelnetConnectionError as e:
            raise DeviceConnectionError(
                device_id=device_id,
                reason=f"Telnet 连接失败: {e}",
            ) from e
        except TelnetCommandError as e:
            raise DeviceConnectionError(
                device_id=device_id,
                reason=f"命令执行失败: {e}",
            ) from e
        finally:
            self.disconnect(device_id)

        return CommandResult(
            device_id=config["id"],
            device_name=config["name"],
            command=command,
            normalized_command=normalized,
            success=True,
            output=output,
            executed_at=datetime.now().isoformat(),
        )

    def run_show_commands(
        self,
        device_id: str,
        commands: list[str],
        timeout_map: Optional[dict[str, float]] = None,
    ) -> list[CommandOutput]:
        """Execute multiple read-only commands in one fresh session."""
        config = self._get_device_config(device_id)

        if config.get("type") == "pc":
            raise DeviceConnectionError(
                device_id=device_id,
                reason=f"设备类型 {config['type']} 不支持命令执行",
            )

        normalized_commands = [check_command(command) for command in commands]
        timeout_map = timeout_map or {}
        outputs: list[CommandOutput] = []

        try:
            client = self._open_fresh_client(device_id, timeout=6.0)
            self._prepare_user_view(client)
            for normalized in normalized_commands:
                try:
                    output = client.send_command(
                        normalized,
                        timeout=timeout_map.get(normalized, 5.0),
                    )
                    outputs.append(CommandOutput(
                        command=normalized,
                        success=True,
                        output=output,
                    ))
                except (TelnetConnectionError, TelnetCommandError) as e:
                    outputs.append(CommandOutput(
                        command=normalized,
                        success=False,
                        error=str(e),
                    ))
        except TelnetConnectionError as e:
            raise DeviceConnectionError(
                device_id=device_id,
                reason=f"Telnet 连接失败: {e}",
            ) from e
        finally:
            self.disconnect(device_id)

        return outputs

    def backup_config(self, device_id: str) -> BackupResult:
        """备份设备配置（只读导出）。"""
        config = self._get_device_config(device_id)

        if config.get("type") == "pc":
            raise DeviceConnectionError(
                device_id=device_id,
                reason=f"设备类型 {config['type']} 不支持配置备份",
            )

        output = ""
        last_error: Optional[Exception] = None
        for _ in range(2):
            try:
                client = self._open_fresh_client(device_id, timeout=12.0)
                self._prepare_user_view(client)
                output = client.send_command(
                    "display current-configuration",
                    timeout=45.0,
                )
                if output.strip():
                    break
                raise TelnetCommandError(
                    "display current-configuration returned empty output"
                )
            except (TelnetConnectionError, TelnetCommandError) as e:
                last_error = e
                output = ""
            finally:
                self.disconnect(device_id)

        if not output.strip():
            raise DeviceConnectionError(
                device_id=device_id,
                reason=f"配置备份失败: {last_error or 'empty output'}",
            ) from last_error

        backup_path = self._build_backup_path(config["name"])
        with open(backup_path, "w", encoding="utf-8") as f:
            f.write(output)

        return BackupResult(
            device_id=config["id"],
            device_name=config["name"],
            success=True,
            backup_path=backup_path,
            backed_up_at=datetime.now().isoformat(),
        )

    # 诊断命令列表
    _DIAGNOSTIC_COMMANDS = [
        "display version",
        "display interface brief",
        "display ip interface brief",
        "display ip routing-table",
        "display ospf peer",
        "display ospf brief",
        "display vlan",
    ]

    _SWITCH_DIAGNOSTIC_COMMANDS = [
        "display version",
        "display interface brief",
        "display vlan",
        "display current-configuration",
        "display ip pool",
        "display dhcp statistics",
    ]

    def get_device_diagnostics(self, device_id: str) -> DeviceDiagnostics:
        """获取单台设备的聚合诊断数据。

        逐条执行诊断命令，单条失败不中断，错误记录在 CommandOutput.error 中。
        """
        config = self._get_device_config(device_id)

        if config.get("type") == "pc":
            raise DeviceConnectionError(
                device_id=device_id,
                reason=f"设备类型 {config['type']} 不支持诊断查询",
            )

        # 根据设备类型选择诊断命令列表
        if config.get("type") == "switch":
            diag_commands = self._SWITCH_DIAGNOSTIC_COMMANDS
        else:
            diag_commands = self._DIAGNOSTIC_COMMANDS

        commands: list[CommandOutput] = []

        try:
            client = self._open_fresh_client(device_id, timeout=15.0)
            self._prepare_user_view(client)
        except (TelnetConnectionError, TelnetCommandError) as e:
            # 连接完全失败，所有命令标记为失败
            for cmd in diag_commands:
                commands.append(CommandOutput(
                    command=cmd,
                    success=False,
                    error=f"连接失败: {e}",
                ))
            return DeviceDiagnostics(
                device_id=config["id"],
                device_name=config["name"],
                collected_at=datetime.now().isoformat(),
                commands=commands,
            )

        for cmd in diag_commands:
            try:
                output = client.send_command(cmd, timeout=45.0)
                commands.append(CommandOutput(
                    command=cmd,
                    success=True,
                    output=output,
                ))
            except (TelnetConnectionError, TelnetCommandError) as e:
                commands.append(CommandOutput(
                    command=cmd,
                    success=False,
                    error=str(e),
                ))
        self.disconnect(device_id)

        return DeviceDiagnostics(
            device_id=config["id"],
            device_name=config["name"],
            collected_at=datetime.now().isoformat(),
            commands=commands,
        )

    def run_config_commands(
        self, device_id: str, commands: list[str]
    ) -> list[ConfigCommandResult]:
        """在真实设备上执行一组配置命令。

        流程：断开旧连接 → 新建连接 → system-view → 逐条执行 → return → 返回结果。
        每条命令独立记录成功/失败，单条失败不中断后续命令。
        """
        config = self._get_device_config(device_id)

        if config.get("type") == "pc":
            raise DeviceConnectionError(
                device_id=device_id,
                reason=f"设备类型 {config['type']} 不支持配置命令",
            )

        try:
            client = self._open_fresh_client(device_id, timeout=15.0)
            self._prepare_user_view(client)
        except (TelnetConnectionError, TelnetCommandError) as e:
            raise DeviceConnectionError(
                device_id=device_id,
                reason=f"配置命令连接失败: {e}",
            ) from e

        # 进入 system-view
        try:
            client.send_command("system-view", timeout=20.0)
        except (TelnetConnectionError, TelnetCommandError) as e:
            raise DeviceConnectionError(
                device_id=device_id,
                reason=f"进入 system-view 失败: {e}",
            ) from e

        # 逐条执行配置命令
        managed_commands = self._build_managed_config_commands(
            config["name"],
            commands,
        )
        results: list[ConfigCommandResult] = []
        for cmd in managed_commands:
            try:
                output = client.send_command(cmd, timeout=30.0)
                results.append(ConfigCommandResult(
                    command=cmd,
                    success=True,
                    output=output,
                ))
            except (TelnetConnectionError, TelnetCommandError) as e:
                results.append(ConfigCommandResult(
                    command=cmd,
                    success=False,
                    error=str(e),
                ))

        # 退出 system-view
        try:
            client.send_command("return", timeout=10.0)
        except (TelnetConnectionError, TelnetCommandError):
            pass  # 退出失败不影响已执行的结果
        finally:
            self.disconnect(device_id)

        return results

    def save_config(self, device_id: str) -> SaveResult:
        """在真实设备上执行 save 命令，保存当前配置。

        流程：断开旧连接 → 新建连接（用户视图）→ 发送 save → 处理确认提示 → 返回结果。
        """
        config = self._get_device_config(device_id)

        if config.get("type") == "pc":
            raise DeviceConnectionError(
                device_id=device_id,
                reason=f"设备类型 {config['type']} 不支持配置保存",
            )

        try:
            client = self._open_fresh_client(device_id, timeout=8.0)
            self._prepare_user_view(client)
        except (TelnetConnectionError, TelnetCommandError) as e:
            raise DeviceConnectionError(
                device_id=device_id,
                reason=f"save 连接失败: {e}",
            ) from e

        try:
            output = client.send_save_command(
                device_type=config["type"],
                device_name=config["name"],
                timeout=20.0,
            )
        except (TelnetConnectionError, TelnetCommandError) as e:
            raise DeviceConnectionError(
                device_id=device_id,
                reason=f"save 命令执行失败: {e}",
            ) from e
        finally:
            self.disconnect(device_id)

        return SaveResult(
            device_id=config["id"],
            device_name=config["name"],
            success=True,
            output=output,
            saved_at=datetime.now().isoformat(),
        )

    def restore_config(self, device_id: str, backup_path: str) -> RestoreResult:
        """从备份文件恢复设备配置（增强实现）。

        当前阶段：VRP 整份配置自动恢复存在安全风险（可能覆盖管理接口、
        导致连接中断），不执行自动化恢复。但会：
        1. 验证备份文件存在性
        2. 验证设备类型兼容性
        3. 验证设备连接可达性（仅探测，不执行恢复命令）
        4. 返回结构化错误码和人工恢复指引
        """
        config = self._get_device_config(device_id)

        if config.get("type") == "pc":
            raise DeviceConnectionError(
                device_id=device_id,
                reason=f"设备类型 {config['type']} 不支持配置恢复",
            )

        # 检查备份文件是否存在
        if not os.path.isfile(backup_path):
            backup_dir = str(get_backups_dir().resolve())
            return RestoreResult(
                device_id=config["id"],
                device_name=config["name"],
                success=False,
                error_code="BACKUP_FILE_MISSING",
                error=f"备份文件不存在: {backup_path}",
                recovery_hint=f"备份文件可能已被清理或路径错误，请检查 {backup_dir} 目录",
                manual_steps=[
                    f"检查 {backup_dir} 目录中是否有 {config['name']} 的备份文件",
                    "如有备份，在 eNSP 中手动导入该配置文件",
                    "如无备份，需要在 eNSP 中手动重新配置设备",
                ],
                backup_path=backup_path,
                restored_at=datetime.now().isoformat(),
            )

        # 尝试连接设备（可达性探测）
        try:
            client = self._get_client(device_id)
            # 发送一条简单命令验证连接可用
            client.send_command("display version")
        except (TelnetConnectionError, TelnetCommandError) as e:
            return RestoreResult(
                device_id=config["id"],
                device_name=config["name"],
                success=False,
                error_code="DEVICE_UNREACHABLE",
                error=f"设备不可达，无法执行恢复: {e}",
                recovery_hint="设备可能已关机或 Telnet 端口不可用，请在 eNSP 中检查设备状态",
                manual_steps=[
                    "在 eNSP 中确认设备是否正在运行",
                    "确认 Telnet 端口配置正确（config/devices.yaml）",
                    "如设备在 eNSP 中正常运行，尝试手动导入备份配置",
                ],
                backup_path=backup_path,
                restored_at=datetime.now().isoformat(),
            )

        # VRP 整份配置恢复风险：管理接口可能被覆盖
        return RestoreResult(
            device_id=config["id"],
            device_name=config["name"],
            success=False,
            error_code="VRP_MANUAL_RESTORE_REQUIRED",
            error=(
                "VRP 设备自动配置恢复当前不支持：整份配置恢复可能导致管理接口"
                "中断，请手动在 eNSP 中恢复备份配置"
            ),
            recovery_hint=(
                "VRP 整份配置恢复会覆盖管理接口（Telnet 连接所用接口），"
                "导致恢复过程中连接中断。建议在 eNSP 图形界面中手动操作。"
            ),
            manual_steps=[
                f"在 eNSP 中打开 {config['name']} 的命令行终端",
                "进入用户视图（<设备名> 提示符）",
                f"使用 FTP/TFTP 导入备份配置文件: {backup_path}",
                "或在 eNSP 图形界面中使用「导入配置」功能",
                "恢复后执行 display current-configuration 验证配置内容",
                "如果管理接口 IP 被修改，需更新 config/devices.yaml 中的连接配置",
            ],
            backup_path=backup_path,
            restored_at=datetime.now().isoformat(),
        )

    def disconnect(self, device_id: str) -> None:
        """断开指定设备的连接。"""
        client = self._clients.pop(device_id, None)
        if client:
            client.close()

    def disconnect_all(self) -> None:
        """断开所有连接。"""
        for client in self._clients.values():
            client.close()
        self._clients.clear()


def _extract_uptime(version_output: str) -> Optional[str]:
    """从 display version 输出中提取 uptime。"""
    for line in version_output.splitlines():
        if "uptime is" in line.lower():
            parts = line.split("uptime is", 1)
            if len(parts) == 2:
                return parts[1].strip()
    return None


def _extract_version(version_output: str) -> Optional[str]:
    """从 display version 输出中提取 VRP 版本。"""
    for line in version_output.splitlines():
        if "version" in line.lower() and "vrp" in line.lower():
            return line.strip()
    return None
