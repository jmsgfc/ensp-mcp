"""Device service for the active eNSP topology.

Responsibilities:
1. Resolve and parse the current .topo file.
2. Optionally merge a sibling config/devices.yaml connection inventory.
3. Expose device operations through the configured adapter.
4. Validate read-only commands before they are sent to devices.
5. Record operations through LogService.
"""

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import threading
import time
from typing import Optional

from backend.adapters.base_adapter import (
    BackupResult,
    BaseAdapter,
    CommandOutput,
    CommandRejectedError,
    CommandResult,
    DeviceConnectionError,
    DeviceDiagnostics,
    DeviceNotFoundError,
    DeviceInfo,
    DeviceStatus,
)
from backend.adapters.mock_adapter import (
    MockAdapter,
    build_devices_from_topology,
    merge_device_info,
)
from backend.adapters.ensp_adapter import ENSPAdapter
from backend.services.log_service import LogService
from backend.topology.config import get_devices_config_path, get_topology_path
from backend.topology.parser import parse_topology
from backend.topology.validator import load_devices_yaml, validate_devices_yaml_against_topology
from backend.utils.security import check_command


def _load_topology_and_yaml() -> tuple[object, list[dict]]:
    """Load the current topology and optional devices.yaml."""
    topo_path = get_topology_path()
    topo = parse_topology(topo_path)

    devices_path = get_devices_config_path()
    sibling_devices = topo_path.resolve().parent / "config" / "devices.yaml"
    if devices_path.resolve() != sibling_devices.resolve() and not sibling_devices.exists():
        return topo, []

    yaml_devices = load_devices_yaml(devices_path)
    validation = validate_devices_yaml_against_topology(topo, yaml_devices)
    if not validation.is_valid:
        return topo, []

    return topo, yaml_devices


def _build_device_list() -> list[DeviceInfo]:
    """Build the device inventory from the active topology and config."""
    topo, yaml_devices = _load_topology_and_yaml()

    topo_devices = build_devices_from_topology(topo)
    if not yaml_devices:
        return [
            DeviceInfo(
                id=device.id,
                name=device.name,
                type=device.device_type,
                vendor=device.vendor,
                model=device.model,
                host="127.0.0.1" if device.com_port else None,
                port=device.com_port or None,
                protocol="telnet" if device.com_port else None,
            )
            for device in topo.devices
        ]

    conn_config = {
        item["name"]: {
            "host": item.get("host"),
            "port": item.get("port"),
            "protocol": item.get("protocol"),
            "username_env": item.get("username_env"),
            "password_env": item.get("password_env"),
        }
        for item in yaml_devices
        if item.get("name")
    }

    return merge_device_info(topo_devices, conn_config)


def _build_real_devices_config() -> list[dict]:
    """构建真实 eNSP 模式使用的设备配置。

    真实模式也以拓扑为主数据源，避免 devices.yaml 与拓扑漂移时
    设备身份信息不一致。
    """
    topo, yaml_devices = _load_topology_and_yaml()
    yaml_by_name = {item["name"]: item for item in yaml_devices if item.get("name")}

    merged_devices: list[dict] = []
    for topo_dev in topo.devices:
        yaml_cfg = yaml_by_name.get(topo_dev.name, {})
        merged_devices.append({
            "id": topo_dev.id,
            "name": topo_dev.name,
            "type": topo_dev.device_type,
            "vendor": topo_dev.vendor,
            "model": topo_dev.model,
            "host": yaml_cfg.get("host") or ("127.0.0.1" if topo_dev.com_port else None),
            "port": yaml_cfg.get("port") or (topo_dev.com_port or None),
            "protocol": yaml_cfg.get("protocol") or ("telnet" if topo_dev.com_port else None),
            "username_env": yaml_cfg.get("username_env"),
            "password_env": yaml_cfg.get("password_env"),
        })

    return merged_devices


@dataclass
class DeviceHealthCheck:
    """单台设备的健康检查结果。"""
    device_name: str
    host_configured: bool
    port_configured: bool
    credential_env_exists: bool
    issues: list[str]


@dataclass
class EnspHealthReport:
    """真实 eNSP 环境健康检查报告。"""
    enabled: bool
    devices: list[DeviceHealthCheck]
    ready: bool
    issues: list[str]


@dataclass
class DeviceDiagSummary:
    """单台设备诊断摘要。"""
    device_name: str
    commands_collected: int
    commands_failed: int
    failed_commands: list[str]


@dataclass
class VerificationSummary:
    """PC1/PC2 连通性验证摘要。"""
    health: EnspHealthReport
    device_diagnostics: list[DeviceDiagSummary]
    successful_devices: list[str]
    failed_devices: list[str]
    connectivity: object  # ConnectivityAnalysis
    next_steps: list[str]


_DHCP_DIAG_CACHE_TTL_SECONDS = 120.0


def check_ensp_health() -> EnspHealthReport:
    """检查真实 eNSP 环境的前置条件。

    只读检查，不尝试连接设备。
    """
    enabled = os.getenv("ENABLE_REAL_ENSP", "false").lower() == "true"
    issues: list[str] = []

    if not enabled:
        return EnspHealthReport(enabled=False, devices=[], ready=False, issues=["ENABLE_REAL_ENSP 未设置为 true"])

    # 加载设备配置
    try:
        devices_config = _build_real_devices_config()
    except Exception as e:
        return EnspHealthReport(enabled=True, devices=[], ready=False, issues=[f"加载设备配置失败: {e}"])

    device_checks: list[DeviceHealthCheck] = []
    routers_only = [d for d in devices_config if d.get("type") != "pc"]

    for cfg in routers_only:
        name = cfg.get("name", "unknown")
        host_ok = bool(cfg.get("host"))
        port_ok = bool(cfg.get("port"))
        device_issues: list[str] = []

        if not host_ok:
            device_issues.append(f"{name} 未配置 host")
            issues.append(f"{name} 未配置 host")
        if not port_ok:
            device_issues.append(f"{name} 未配置 port")
            issues.append(f"{name} 未配置 port")

        device_checks.append(DeviceHealthCheck(
            device_name=name,
            host_configured=host_ok,
            port_configured=port_ok,
            # eNSP 实验环境允许无账号密码直登，凭据缺失不再阻塞健康检查。
            credential_env_exists=True,
            issues=device_issues,
        ))

    return EnspHealthReport(
        enabled=True,
        devices=device_checks,
        ready=len(issues) == 0,
        issues=issues,
    )


def _create_adapter(log_service: LogService) -> BaseAdapter:
    """根据环境变量决定使用哪个适配器。

    当前阶段默认使用 MockAdapter。
    只有当 ENABLE_REAL_ENSP=true 且 ENSP 连接逻辑已实现时，
    才会尝试使用 ENSPAdapter。
    """
    enable_real = os.getenv("ENABLE_REAL_ENSP", "false").lower() == "true"

    if enable_real:
        from backend.adapters.ensp_adapter import ENSPAdapter
        devices_config = _build_real_devices_config()
        return ENSPAdapter(devices_config=devices_config, enable_real=True)

    devices = _build_device_list()
    return MockAdapter(devices=devices)


class DeviceService:
    """设备服务，对外暴露设备查询能力。"""

    def __init__(self, log_service: LogService):
        self._log_service = log_service
        self._adapter = _create_adapter(log_service)
        self._dhcp_diag_cache: dict[tuple[str, str], tuple[float, DeviceDiagnostics]] = {}
        self._dhcp_diag_cache_lock = threading.Lock()
        self._dhcp_diag_cache_source = self._build_dhcp_cache_source_key()

    @property
    def adapter(self) -> BaseAdapter:
        return self._adapter

    def refresh_adapter(self) -> None:
        """Reload topology-backed device data for the current MCP call."""
        self._adapter = _create_adapter(self._log_service)
        self._sync_dhcp_cache_source()

    def invalidate_dhcp_cache(self) -> None:
        with self._dhcp_diag_cache_lock:
            self._dhcp_diag_cache.clear()
            self._dhcp_diag_cache_source = self._build_dhcp_cache_source_key()

    def _build_dhcp_cache_source_key(self) -> tuple[str, float, str, float]:
        topo_path = get_topology_path().resolve()
        devices_path = get_devices_config_path().resolve()
        topo_mtime = topo_path.stat().st_mtime if topo_path.exists() else 0.0
        devices_mtime = devices_path.stat().st_mtime if devices_path.exists() else 0.0
        return (str(topo_path), topo_mtime, str(devices_path), devices_mtime)

    def _sync_dhcp_cache_source(self) -> None:
        current_source = self._build_dhcp_cache_source_key()
        with self._dhcp_diag_cache_lock:
            if current_source != self._dhcp_diag_cache_source:
                self._dhcp_diag_cache.clear()
                self._dhcp_diag_cache_source = current_source

    @staticmethod
    def _build_dhcp_cache_key(device: DeviceInfo) -> tuple[str, str]:
        return (device.id, device.name)

    def _get_cached_dhcp_diagnostics(
        self, device: DeviceInfo
    ) -> Optional[DeviceDiagnostics]:
        cache_key = self._build_dhcp_cache_key(device)
        now = time.time()
        with self._dhcp_diag_cache_lock:
            cached = self._dhcp_diag_cache.get(cache_key)
            if cached is None:
                return None
            cached_at, diagnostics = cached
            if now - cached_at > _DHCP_DIAG_CACHE_TTL_SECONDS:
                self._dhcp_diag_cache.pop(cache_key, None)
                return None
            return diagnostics

    def _store_cached_dhcp_diagnostics(
        self, device: DeviceInfo, diagnostics: DeviceDiagnostics
    ) -> None:
        if not diagnostics.commands or any(not cmd.success for cmd in diagnostics.commands):
            return
        cache_key = self._build_dhcp_cache_key(device)
        with self._dhcp_diag_cache_lock:
            self._dhcp_diag_cache[cache_key] = (time.time(), diagnostics)

    def list_devices(self) -> list[DeviceInfo]:
        """列出所有设备。"""
        devices = self._adapter.list_devices()
        self._log_service.log_device_list(count=len(devices))
        return devices

    def get_device_status(self, device_id: str) -> DeviceStatus:
        """查询设备运行状态。"""
        device_name = self._resolve_device_name(device_id)

        try:
            status = self._adapter.get_device_status(device_id)
            self._log_service.log_device_status(
                device_id=device_id,
                device_name=device_name,
                success=True,
                detail="设备状态查询成功",
            )
            return status
        except DeviceNotFoundError as e:
            self._log_service.log_device_status(
                device_id=device_id,
                device_name=device_name,
                success=False,
                detail=str(e),
            )
            raise
        except DeviceConnectionError as e:
            self._log_service.log_connection_error(
                device_id=device_id,
                device_name=device_name,
                reason=str(e),
            )
            raise
        except NotImplementedError as e:
            self._log_service.log_device_status(
                device_id=device_id,
                device_name=device_name,
                success=False,
                detail=str(e),
            )
            raise
        except Exception as e:
            self._log_service.log_device_status(
                device_id=device_id,
                device_name=device_name,
                success=False,
                detail=f"未知错误: {e}",
            )
            raise

    def run_command(self, device_id: str, command: str) -> CommandResult:
        """执行一条只读命令（经过白名单校验）。"""
        device_name = self._resolve_device_name(device_id)

        try:
            normalized = check_command(command)
        except CommandRejectedError as e:
            self._log_service.log_command_rejected(
                command=command,
                reason=e.reason,
            )
            raise

        try:
            result = self._adapter.run_show_command(device_id, normalized)
            self._log_service.log_command_exec(
                device_id=device_id,
                device_name=device_name,
                command=normalized,
                success=True,
                detail="命令执行成功",
            )
            return result
        except DeviceNotFoundError as e:
            self._log_service.log_command_exec(
                device_id=device_id,
                device_name=device_name,
                command=command,
                success=False,
                detail=str(e),
            )
            raise
        except DeviceConnectionError as e:
            self._log_service.log_connection_error(
                device_id=device_id,
                device_name=device_name,
                reason=str(e),
            )
            raise
        except NotImplementedError as e:
            self._log_service.log_command_exec(
                device_id=device_id,
                device_name=device_name,
                command=command,
                success=False,
                detail=str(e),
            )
            raise
        except Exception as e:
            self._log_service.log_command_exec(
                device_id=device_id,
                device_name=device_name,
                command=command,
                success=False,
                detail=f"未知错误: {e}",
            )
            raise

    def get_device_current_config(self, device_id: str) -> CommandResult:
        """读取设备当前配置，不记录成功日志，适合高频轮询场景。"""
        device_name = self._resolve_device_name(device_id)
        normalized = check_command("display current-configuration")

        try:
            return self._adapter.run_show_command(device_id, normalized)
        except DeviceNotFoundError:
            raise
        except DeviceConnectionError as e:
            self._log_service.log_connection_error(
                device_id=device_id,
                device_name=device_name,
                reason=str(e),
            )
            raise
        except NotImplementedError:
            raise
        except Exception as e:
            self._log_service.log_connection_error(
                device_id=device_id,
                device_name=device_name,
                reason=f"读取当前配置失败: {e}",
            )
            raise

    def backup_config(self, device_id: str) -> BackupResult:
        """备份设备配置。"""
        device_name = self._resolve_device_name(device_id)

        try:
            result = self._adapter.backup_config(device_id)
            self._log_service.log_config_backup(
                device_id=device_id,
                device_name=device_name,
                success=True,
                detail="配置备份成功",
            )
            return result
        except DeviceNotFoundError as e:
            self._log_service.log_config_backup(
                device_id=device_id,
                device_name=device_name,
                success=False,
                detail=str(e),
            )
            raise
        except DeviceConnectionError as e:
            self._log_service.log_connection_error(
                device_id=device_id,
                device_name=device_name,
                reason=str(e),
            )
            raise
        except NotImplementedError as e:
            self._log_service.log_config_backup(
                device_id=device_id,
                device_name=device_name,
                success=False,
                detail=str(e),
            )
            raise
        except Exception as e:
            self._log_service.log_config_backup(
                device_id=device_id,
                device_name=device_name,
                success=False,
                detail=f"未知错误: {e}",
            )
            raise

    def get_device_diagnostics(self, device_id: str) -> DeviceDiagnostics:
        """获取单台设备的聚合诊断数据。"""
        device_name = self._resolve_device_name(device_id)

        try:
            result = self._adapter.get_device_diagnostics(device_id)
            self._log_service.log_device_status(
                device_id=device_id,
                device_name=device_name,
                success=True,
                detail="设备诊断查询成功",
            )
            return result
        except DeviceNotFoundError as e:
            self._log_service.log_device_status(
                device_id=device_id,
                device_name=device_name,
                success=False,
                detail=str(e),
            )
            raise
        except DeviceConnectionError as e:
            self._log_service.log_connection_error(
                device_id=device_id,
                device_name=device_name,
                reason=str(e),
            )
            raise

    def get_topology_diagnostics(self) -> list[DeviceDiagnostics]:
        """获取所有路由器的聚合诊断数据。

        跳过 PC 类型设备。单台设备失败不中断整体诊断。
        """
        devices = self._adapter.list_devices()
        results: list[DeviceDiagnostics] = []

        for device in devices:
            if device.type == "pc":
                continue
            try:
                diag = self.get_device_diagnostics(device.id)
                results.append(diag)
            except (DeviceConnectionError, DeviceNotFoundError) as e:
                # 构造一个失败占位结果
                from backend.adapters.base_adapter import CommandOutput
                results.append(DeviceDiagnostics(
                    device_id=device.id,
                    device_name=device.name,
                    collected_at=datetime.now().isoformat(),
                    commands=[CommandOutput(
                        command="<connection>",
                        success=False,
                        error=str(e),
                    )],
                ))

        return results

    def get_dhcp_diagnostics(self) -> list[DeviceDiagnostics]:
        """Collect only the switch-side diagnostics required by DHCP workflows."""
        self._sync_dhcp_cache_source()
        from backend.services.dhcp_analysis import build_dhcp_config_probe_commands

        def collect_device_diagnostics(device: DeviceInfo) -> DeviceDiagnostics:
            cached = self._get_cached_dhcp_diagnostics(device)
            if cached is not None:
                return cached

            config_probe_commands = build_dhcp_config_probe_commands(device.name)
            dhcp_commands = ["display vlan", *config_probe_commands]
            if device.name == "LSW1":
                dhcp_commands.extend([
                    "display ip pool",
                    "display dhcp statistics",
                ])

            command_outputs: list[CommandOutput] = []
            batch_runner = getattr(self._adapter, "run_show_commands", None)
            if callable(batch_runner):
                try:
                    timeout_map = {
                        "display vlan": 2.0,
                        "display current-configuration": 12.0,
                        "display ip pool": 2.0,
                        "display dhcp statistics": 2.0,
                    }
                    for command in config_probe_commands:
                        timeout_map[command] = 3.0
                    command_outputs = batch_runner(
                        device.id,
                        dhcp_commands,
                        timeout_map=timeout_map,
                    )
                except (DeviceConnectionError, DeviceNotFoundError) as e:
                    command_outputs = [
                        CommandOutput(command=command, success=False, error=str(e))
                        for command in dhcp_commands
                    ]
            else:
                for command in dhcp_commands:
                    try:
                        result = self.run_command(device.id, command)
                        command_outputs.append(CommandOutput(
                            command=command,
                            success=True,
                            output=result.output,
                        ))
                    except (DeviceConnectionError, DeviceNotFoundError) as e:
                        command_outputs.append(CommandOutput(
                            command=command,
                            success=False,
                            error=str(e),
                        ))

            if config_probe_commands:
                config_parts = [
                    output.output
                    for output in command_outputs
                    if output.command in config_probe_commands and output.success and output.output
                ]
                config_failures = [
                    f"{output.command}: {output.error}"
                    for output in command_outputs
                    if output.command in config_probe_commands and not output.success
                ]
                command_outputs.append(CommandOutput(
                    command="display current-configuration",
                    success=not config_failures,
                    output="\n".join(config_parts) if config_parts else None,
                    error="; ".join(config_failures) if config_failures else None,
                ))

            diagnostics = DeviceDiagnostics(
                device_id=device.id,
                device_name=device.name,
                collected_at=datetime.now().isoformat(),
                commands=command_outputs,
            )
            self._store_cached_dhcp_diagnostics(device, diagnostics)
            return diagnostics

        switches = [
            device for device in self._adapter.list_devices()
            if device.type == "switch"
        ]
        if not switches:
            return []

        max_workers = min(4, len(switches))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            return list(executor.map(collect_device_diagnostics, switches))

    def analyze_pc_connectivity(self):
        """分析 PC1/PC2 连通性。

        获取 AR1/AR2/AR3 的诊断数据，调用分析模块判断互通条件。
        """
        from backend.services.connectivity_analysis import (
            ConnectivityAnalysis,
            analyze_pc_connectivity as _analyze,
        )

        diags = self.get_topology_diagnostics()
        self._log_service.log_device_status(
            device_id="<analysis>",
            device_name="PC1/PC2 连通性分析",
            success=True,
            detail="连通性分析完成",
        )
        return _analyze(diags)

    def get_verification_summary(self) -> "VerificationSummary":
        """获取 PC1/PC2 连通性验证摘要。

        汇总健康检查、诊断、连通性分析结果，返回一份验证视图。
        """
        from backend.services.connectivity_analysis import (
            analyze_pc_connectivity as _analyze,
        )

        # 1. 健康检查
        health = check_ensp_health()

        # 2. 诊断结果
        diags = self.get_topology_diagnostics()
        device_results: list[DeviceDiagSummary] = []
        successful_devices: list[str] = []
        failed_devices: list[str] = []

        for diag in diags:
            has_error = any(not c.success for c in diag.commands)
            error_commands = [c.command for c in diag.commands if not c.success]
            device_results.append(DeviceDiagSummary(
                device_name=diag.device_name,
                commands_collected=len([c for c in diag.commands if c.success]),
                commands_failed=len(error_commands),
                failed_commands=error_commands,
            ))
            if has_error and diag.commands[0].command == "<connection>":
                failed_devices.append(diag.device_name)
            else:
                successful_devices.append(diag.device_name)

        # 3. 连通性分析
        connectivity = _analyze(diags)

        # 4. 生成建议下一步
        next_steps: list[str] = []
        if not health.enabled:
            next_steps.append("设置 ENABLE_REAL_ENSP=true 以启用真实 eNSP 模式")
        elif not health.ready:
            next_steps.append("修复健康检查中的问题（见 health.issues）")
        elif failed_devices:
            next_steps.append(f"修复设备连接问题: {', '.join(failed_devices)}")
        elif connectivity.gaps:
            next_steps.append("根据 connectivity.gaps 中的缺口配置设备路由")
        elif connectivity.pc1_to_pc2_reachable and connectivity.pc2_to_pc1_reachable:
            next_steps.append("PC1 与 PC2 已可互通，验证完成")
        else:
            next_steps.append("检查 connectivity.gaps 和 connectivity.config_suggestions")

        return VerificationSummary(
            health=health,
            device_diagnostics=device_results,
            successful_devices=successful_devices,
            failed_devices=failed_devices,
            connectivity=connectivity,
            next_steps=next_steps,
        )

    def _resolve_device_name(self, device_id: str) -> str:
        """解析设备名，找不到时返回设备 ID。"""
        devices = self._adapter.list_devices()
        for d in devices:
            if d.id == device_id:
                return d.name
        return device_id
