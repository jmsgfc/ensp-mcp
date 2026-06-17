"""eNSP-MCP 管理平台 FastAPI 入口。

提供以下 API：
- GET  /api/devices                    获取设备列表
- GET  /api/devices/{device_id}/status 查询设备状态
- POST /api/devices/{device_id}/commands/run  执行只读命令
- GET  /api/logs                       查询操作日志

当前默认使用 MockAdapter，不连接真实 eNSP。
"""

import dataclasses
import os
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# 加载 .env 文件（如果存在）
load_dotenv()

from backend.adapters.base_adapter import (
    CommandRejectedError,
    DeviceConnectionError,
    DeviceDiagnostics,
    DeviceNotFoundError,
)
from backend.services.device_service import DeviceService
from backend.services.log_service import LogService, LogLevel, LogAction
from backend.runtime.context import get_device_service, get_log_service
from backend.topology.config import get_topology_path
from backend.topology.interface_mapping import interface_name
from backend.topology.parser import parse_topology

# 初始化服务（从共享上下文获取，与 MCP 层共用同一实例）
log_service = get_log_service()
device_service = get_device_service()

# FastAPI 应用
app = FastAPI(
    title="eNSP-MCP 管理平台",
    description="将大模型安全接入 eNSP 实验网络的 MCP 管理平台",
    version="0.1.0",
)

# 静态文件挂载（HTML 调试页）
_static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")


# --- 请求/响应模型 ---

@app.get("/api/topology/graph")
def topology_graph():
    """Return the active .topo as graph data for the HTML topology view."""
    topo = parse_topology(get_topology_path())
    devices_by_id = {device.id: device for device in topo.devices}

    devices = [
        {
            "id": device.id,
            "name": device.name,
            "type": device.device_type,
            "model": device.model,
            "vendor": device.vendor,
            "x": device.cx,
            "y": device.cy,
            "host": "127.0.0.1" if device.com_port else None,
            "port": device.com_port or None,
            "protocol": "telnet" if device.com_port else None,
        }
        for device in topo.devices
    ]

    links = []
    for index, link in enumerate(topo.links):
        source = devices_by_id.get(link.src_device_id)
        target = devices_by_id.get(link.dest_device_id)
        if source is None or target is None:
            continue
        links.append({
            "id": f"link-{index + 1}",
            "source": source.id,
            "target": target.id,
            "source_name": source.name,
            "target_name": target.name,
            "source_interface": interface_name(source, link.src_index),
            "target_interface": interface_name(target, link.tar_index),
            "line_name": link.line_name,
        })

    return {
        "topology": str(get_topology_path()),
        "device_count": len(devices),
        "link_count": len(links),
        "devices": devices,
        "links": links,
    }


class CommandRequest(BaseModel):
    """命令执行请求。"""
    command: str


class DeviceInfoResponse(BaseModel):
    """设备信息响应。"""
    id: str
    name: str
    type: str
    vendor: str
    model: str
    host: Optional[str] = None
    port: Optional[int] = None
    protocol: Optional[str] = None


class DeviceStatusResponse(BaseModel):
    """设备状态响应。"""
    device_id: str
    device_name: str
    is_online: bool
    uptime: Optional[str] = None
    cpu_usage: Optional[str] = None
    memory_usage: Optional[str] = None
    version: Optional[str] = None
    checked_at: Optional[str] = None


class CommandResultResponse(BaseModel):
    """命令执行结果响应。"""
    device_id: str
    device_name: str
    command: str
    normalized_command: str
    success: bool
    output: str
    error: Optional[str] = None
    executed_at: Optional[str] = None


class DeviceCurrentConfigResponse(BaseModel):
    """设备当前配置响应。"""
    device_id: str
    device_name: str
    config: str
    fetched_at: Optional[str] = None


class LogEntryResponse(BaseModel):
    """日志条目响应。"""
    id: int
    timestamp: str
    level: str
    action: str
    device_id: Optional[str] = None
    device_name: Optional[str] = None
    command: Optional[str] = None
    detail: str
    success: bool


class CommandOutputResponse(BaseModel):
    """单条命令诊断输出响应。"""
    command: str
    success: bool
    output: Optional[str] = None
    error: Optional[str] = None


class DeviceDiagnosticsResponse(BaseModel):
    """单台设备诊断聚合响应。"""
    device_id: str
    device_name: str
    collected_at: str
    commands: list[CommandOutputResponse]


class InterfaceStatusResponse(BaseModel):
    """接口状态响应。"""
    name: str
    phy_up: bool
    protocol_up: bool
    ip_address: Optional[str] = None
    status: Optional[str] = None


class RouteEntryResponse(BaseModel):
    """路由条目响应。"""
    destination: str
    mask: str
    proto: str
    next_hop: Optional[str] = None
    interface: Optional[str] = None


class DeviceAnalysisResponse(BaseModel):
    """单设备分析响应。"""
    device_name: str
    interfaces: list[InterfaceStatusResponse]
    routes: list[RouteEntryResponse]
    issues: list[str]


class ConnectivityAnalysisResponse(BaseModel):
    """PC1/PC2 连通性分析响应。"""
    pc1_network: str
    pc2_network: str
    path: list[str]
    device_analyses: list[DeviceAnalysisResponse]
    pc1_to_pc2_reachable: Optional[bool] = None
    pc2_to_pc1_reachable: Optional[bool] = None
    gaps: list[str]
    config_suggestions: list[str]


class OspfPeerResponse(BaseModel):
    """OSPF 邻居响应。"""
    router_id: str
    address: str
    state: str
    interface: Optional[str] = None


class OspfDeviceAnalysisResponse(BaseModel):
    """单台设备 OSPF 分析响应。"""
    device_name: str
    ospf_process_id: Optional[int] = None
    router_id: Optional[str] = None
    area: Optional[str] = None
    peers: list[OspfPeerResponse]
    ospf_routes: list[RouteEntryResponse]
    interfaces_advertised: list[str]
    issues: list[str]


class OspfAnalysisResponse(BaseModel):
    """OSPF 分析响应。"""
    device_analyses: list[OspfDeviceAnalysisResponse]
    all_peers_full: Optional[bool] = None
    all_networks_advertised: Optional[bool] = None
    gaps: list[str]
    config_suggestions: list[str]


class VlanEntryResponse(BaseModel):
    """VLAN 条目响应。"""
    vlan_id: int
    vlan_type: str
    ports: list[str]


class VlanDeviceAnalysisResponse(BaseModel):
    """单台设备 VLAN 分析响应。"""
    device_name: str
    vlans: list[VlanEntryResponse]
    issues: list[str]


class VlanAnalysisResponse(BaseModel):
    """VLAN 分析响应。"""
    device_analyses: list[VlanDeviceAnalysisResponse]
    all_vlans_configured: Optional[bool] = None
    all_ports_assigned: Optional[bool] = None
    gaps: list[str]
    config_suggestions: list[str]


# --- DHCP 分析响应模型 ---

class DhcpPoolResponse(BaseModel):
    """DHCP 地址池响应。"""
    name: str
    network: str
    gateway: str
    mask: Optional[str] = None
    lease: Optional[str] = None


class VlanifResponse(BaseModel):
    """Vlanif 接口响应。"""
    vlan_id: int
    ip_address: Optional[str] = None
    subnet_mask: Optional[str] = None
    dhcp_select: Optional[str] = None


class DhcpSwitchAnalysisResponse(BaseModel):
    """单台交换机 DHCP 分析响应。"""
    device_name: str
    device_type: str
    vlans: list[int]
    vlanifs: list[VlanifResponse]
    dhcp_enabled: Optional[bool] = None
    dhcp_pools: list[DhcpPoolResponse]
    access_ports: dict[str, int]
    trunk_ports: dict[str, list[int]]
    issues: list[str]


class DhcpAnalysisResponse(BaseModel):
    """DHCP 分析响应。"""
    device_analyses: list[DhcpSwitchAnalysisResponse]
    all_vlans_configured: Optional[bool] = None
    all_vlanifs_configured: Optional[bool] = None
    dhcp_fully_configured: Optional[bool] = None
    all_ports_correct: Optional[bool] = None
    gaps: list[str]
    config_suggestions: list[str]


class DeviceHealthCheckResponse(BaseModel):
    """单台设备健康检查响应。"""
    device_name: str
    host_configured: bool
    port_configured: bool
    credential_env_exists: bool
    issues: list[str]


class EnspHealthReportResponse(BaseModel):
    """eNSP 环境健康检查响应。"""
    enabled: bool
    devices: list[DeviceHealthCheckResponse]
    ready: bool
    issues: list[str]


class DeviceDiagSummaryResponse(BaseModel):
    """单台设备诊断摘要响应。"""
    device_name: str
    commands_collected: int
    commands_failed: int
    failed_commands: list[str]


class VerificationSummaryResponse(BaseModel):
    """PC1/PC2 连通性验证摘要响应。"""
    health: EnspHealthReportResponse
    device_diagnostics: list[DeviceDiagSummaryResponse]
    successful_devices: list[str]
    failed_devices: list[str]
    connectivity: ConnectivityAnalysisResponse
    next_steps: list[str]


class ConfigCommandDraftResponse(BaseModel):
    """单台设备配置命令草案响应。"""
    device_name: str
    commands: list[str]
    purpose: str
    risk_level: str
    risk_warning: str


class ConfigDraftResponse(BaseModel):
    """配置草案预览响应。"""
    draft_id: str
    created_at: str
    purpose: str
    devices: list[ConfigCommandDraftResponse]
    risk_summary: str
    warnings: list[str]
    requires_confirmation: bool


class ConfigApplyRequest(BaseModel):
    """配置下发请求。"""
    confirmed: bool = False
    draft_id: Optional[str] = None


class ConfigCommandResultResponse(BaseModel):
    """单条配置命令执行结果响应。"""
    command: str
    success: bool
    output: Optional[str] = None
    error: Optional[str] = None


class DeviceDeployResultResponse(BaseModel):
    """单台设备执行结果响应。"""
    device_id: str
    device_name: str
    backup_success: bool
    backup_error: Optional[str] = None
    command_results: list[ConfigCommandResultResponse]
    all_commands_success: bool
    error: Optional[str] = None


class VerificationResultResponse(BaseModel):
    """执行后验证结果响应。"""
    pc1_to_pc2_reachable: bool
    pc2_to_pc1_reachable: bool
    gaps: list[str]
    verified_at: str


class ConfigDeployResultResponse(BaseModel):
    """配置下发结果响应。"""
    draft_id: str
    success: bool
    device_results: list[DeviceDeployResultResponse]
    verification: Optional[VerificationResultResponse] = None
    deployed_at: str
    error: Optional[str] = None


class LatestDeploySummaryResponse(BaseModel):
    """最近一次部署结果摘要。"""
    draft_id: str
    deployed_at: str
    device_count: int
    all_backup_success: bool
    all_commands_success: bool
    overall_success: bool
    verification_passed: Optional[bool] = None
    device_names: list[str]


class FinalReportResponse(BaseModel):
    """最终验证报告响应。"""
    health: EnspHealthReportResponse
    diagnostics: list[DeviceDiagnosticsResponse]
    connectivity: ConnectivityAnalysisResponse
    latest_deploy: Optional[LatestDeploySummaryResponse] = None
    save_status: Optional[str] = None
    rollback_status: Optional[str] = None
    final_status: str
    summary: str
    next_steps: list[str]
    generated_at: str


class SaveApplyRequest(BaseModel):
    """配置保存请求。"""
    confirmed: bool = False


class DeviceSaveResultResponse(BaseModel):
    """单台设备保存结果响应。"""
    device_id: str
    device_name: str
    success: bool
    output: Optional[str] = None
    error: Optional[str] = None


class SaveAllResultResponse(BaseModel):
    """批量保存结果响应。"""
    success: bool
    device_results: list[DeviceSaveResultResponse]
    saved_at: str
    error: Optional[str] = None


class DeviceRollbackInfoResponse(BaseModel):
    """单台设备回滚信息响应。"""
    device_id: str
    device_name: str
    backup_path: Optional[str] = None
    has_backup: bool


class RollbackPreviewResponse(BaseModel):
    """回滚预览响应。"""
    available: bool
    devices: list[DeviceRollbackInfoResponse]
    warnings: list[str]
    requires_confirmation: bool
    reason: Optional[str] = None


class RollbackApplyRequest(BaseModel):
    """回滚请求。"""
    confirmed: bool = False


class DeviceRollbackResultResponse(BaseModel):
    """单台设备回滚结果响应。"""
    device_id: str
    device_name: str
    success: bool
    output: Optional[str] = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    recovery_hint: Optional[str] = None
    manual_steps: Optional[list[str]] = None
    backup_path: Optional[str] = None


class RollbackResultResponse(BaseModel):
    """回滚结果响应。"""
    success: bool
    device_results: list[DeviceRollbackResultResponse]
    verification: Optional[VerificationResultResponse] = None
    rolled_back_at: str
    error: Optional[str] = None


class PcDhcpVerificationResponse(BaseModel):
    """单台 PC 的 DHCP 验证结果响应。"""
    pc_name: str
    expected_vlan: int
    expected_subnet: str
    expected_mask: str
    expected_gateway: str
    actual_ip: Optional[str] = None
    actual_mask: Optional[str] = None
    actual_gateway: Optional[str] = None
    ip_in_expected_subnet: bool = False
    mask_ok: bool = False
    gateway_ok: bool = False
    dhcp_enabled: bool = False
    status: str


class DhcpFinalReportResponse(BaseModel):
    """DHCP 最终验证报告响应。"""
    available: bool
    verification_mode: str
    pc_results: list[PcDhcpVerificationResponse]
    all_success: bool
    summary: str
    note: Optional[str] = None


class NlPlanRequest(BaseModel):
    """自然语言配置计划请求。"""
    request: str


class NlDeviceDraftResponse(BaseModel):
    """单台设备草案响应。"""
    device_id: str
    device_name: str
    commands: list[str]
    purpose: str
    risk_level: str
    risk_warning: str


class NlDraftResponse(BaseModel):
    """草案响应。"""
    draft_id: str
    created_at: str
    purpose: str
    risk_summary: str
    warnings: list[str]
    requires_confirmation: bool
    devices: list[NlDeviceDraftResponse]


class NlPlanResponseModel(BaseModel):
    """自然语言配置计划响应。"""
    user_request: str
    intent_type: str
    supported: bool
    summary: str
    target_devices: list[str]
    draft_type: str
    confidence: float
    draft: Optional[NlDraftResponse] = None
    warnings: list[str]
    next_action: str
    reason: str
    error_message: str = ""


# --- API 路由 ---

@app.get("/api/devices", response_model=list[DeviceInfoResponse])
def list_devices():
    """获取所有设备列表。"""
    devices = device_service.list_devices()
    return [
        DeviceInfoResponse(
            id=d.id,
            name=d.name,
            type=d.type,
            vendor=d.vendor,
            model=d.model,
            host=d.host,
            port=d.port,
            protocol=d.protocol,
        )
        for d in devices
    ]


@app.get("/api/devices/{device_id}/status", response_model=DeviceStatusResponse)
def get_device_status(device_id: str):
    """查询指定设备的运行状态。"""
    try:
        status = device_service.get_device_status(device_id)
        return DeviceStatusResponse(
            device_id=status.device_id,
            device_name=status.device_name,
            is_online=status.is_online,
            uptime=status.uptime,
            cpu_usage=status.cpu_usage,
            memory_usage=status.memory_usage,
            version=status.version,
            checked_at=status.checked_at,
        )
    except DeviceNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except DeviceConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except NotImplementedError as e:
        raise HTTPException(status_code=501, detail=str(e))


@app.post("/api/devices/{device_id}/commands/run", response_model=CommandResultResponse)
def run_command(device_id: str, req: CommandRequest):
    """在指定设备上执行一条只读命令。"""
    try:
        result = device_service.run_command(device_id, req.command)
        return CommandResultResponse(
            device_id=result.device_id,
            device_name=result.device_name,
            command=result.command,
            normalized_command=result.normalized_command,
            success=result.success,
            output=result.output,
            error=result.error,
            executed_at=result.executed_at,
        )
    except DeviceNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except CommandRejectedError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except DeviceConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except NotImplementedError as e:
        raise HTTPException(status_code=501, detail=str(e))


@app.get("/api/devices/{device_id}/current-config", response_model=DeviceCurrentConfigResponse)
def get_device_current_config(device_id: str):
    """读取指定设备的当前配置，适合 HTML 看板轮询。"""
    try:
        result = device_service.get_device_current_config(device_id)
        return DeviceCurrentConfigResponse(
            device_id=result.device_id,
            device_name=result.device_name,
            config=result.output,
            fetched_at=result.executed_at,
        )
    except DeviceNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except DeviceConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except NotImplementedError as e:
        raise HTTPException(status_code=501, detail=str(e))


@app.get("/api/health/ensp", response_model=EnspHealthReportResponse)
def health_check_ensp():
    """检查真实 eNSP 环境的前置条件。

    只读检查，不尝试连接设备。
    返回：是否启用真实模式、设备配置完整性、凭据环境变量是否存在。
    """
    from backend.services.device_service import check_ensp_health

    report = check_ensp_health()
    return EnspHealthReportResponse(
        enabled=report.enabled,
        devices=[
            DeviceHealthCheckResponse(
                device_name=d.device_name,
                host_configured=d.host_configured,
                port_configured=d.port_configured,
                credential_env_exists=d.credential_env_exists,
                issues=d.issues,
            )
            for d in report.devices
        ],
        ready=report.ready,
        issues=report.issues,
    )


@app.get("/api/devices/{device_id}/diagnostics", response_model=DeviceDiagnosticsResponse)
def get_device_diagnostics(device_id: str):
    """获取单台设备的聚合诊断数据。"""
    try:
        diag = device_service.get_device_diagnostics(device_id)
        return _to_diagnostics_response(diag)
    except DeviceNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except DeviceConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.get("/api/diagnostics", response_model=list[DeviceDiagnosticsResponse])
def get_topology_diagnostics():
    """获取所有路由器的聚合诊断数据。"""
    diags = device_service.get_topology_diagnostics()
    return [_to_diagnostics_response(d) for d in diags]


@app.get("/api/analysis/pc-connectivity", response_model=ConnectivityAnalysisResponse)
def analyze_pc_connectivity():
    """分析 PC1/PC2 连通性。

    获取 AR1/AR2/AR3 的诊断数据，分析互通条件，输出结构化结果和配置建议草案。
    不执行任何配置下发。
    """
    try:
        result = device_service.analyze_pc_connectivity()
        return _to_connectivity_response(result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"分析失败: {e}")


@app.get("/api/verification/pc-connectivity-summary", response_model=VerificationSummaryResponse)
def verification_summary():
    """获取 PC1/PC2 连通性验证摘要。

    汇总健康检查、诊断、连通性分析结果，返回一份验证视图。
    只读操作，不执行任何配置。
    """
    try:
        summary = device_service.get_verification_summary()
        return _to_verification_response(summary)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取验证摘要失败: {e}")


@app.get("/api/config/pc-connectivity/preview", response_model=Optional[ConfigDraftResponse])
def config_preview():
    """获取 PC1/PC2 互通静态路由配置草案预览。

    基于当前连通性分析结果，生成最小静态路由配置草案。
    只读操作，不执行任何配置。如连通性已满足则返回 null。
    """
    try:
        from backend.services.config_deploy_service import generate_pc_connectivity_draft

        connectivity = device_service.analyze_pc_connectivity()
        draft = generate_pc_connectivity_draft(device_service.adapter, connectivity)

        if draft is None:
            return None

        log_service.log_config_preview(draft.draft_id, len(draft.devices))

        return ConfigDraftResponse(
            draft_id=draft.draft_id,
            created_at=draft.created_at,
            purpose=draft.purpose,
            devices=[
                ConfigCommandDraftResponse(
                    device_name=d.device_name,
                    commands=d.commands,
                    purpose=d.purpose,
                    risk_level=d.risk_level,
                    risk_warning=d.risk_warning,
                )
                for d in draft.devices
            ],
            risk_summary=draft.risk_summary,
            warnings=draft.warnings,
            requires_confirmation=draft.requires_confirmation,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成配置草案失败: {e}")


@app.post("/api/config/pc-connectivity/apply", response_model=ConfigDeployResultResponse)
def config_apply(req: ConfigApplyRequest):
    """执行 PC1/PC2 互通静态路由配置下发。

    安全条件（必须同时满足）：
    1. 请求体 confirmed=true
    2. ENABLE_REAL_ENSP=true
    3. 仅执行系统生成的静态路由草案

    执行流程：
    1. 生成配置草案
    2. 白名单校验所有命令
    3. 每台设备执行前自动备份
    4. 逐设备逐条执行配置命令
    5. 执行后自动验证 PC1/PC2 连通性
    """
    try:
        from backend.services.config_deploy_service import (
            apply_config_draft,
            generate_pc_connectivity_draft,
            get_cached_draft,
            verify_after_deploy,
        )

        # 检查 ENABLE_REAL_ENSP
        import os
        enable_real = os.getenv("ENABLE_REAL_ENSP", "false").lower() == "true"
        if not enable_real:
            return ConfigDeployResultResponse(
                draft_id="",
                success=False,
                device_results=[],
                verification=None,
                deployed_at="",
                error="ENABLE_REAL_ENSP 未启用，拒绝执行配置下发",
            )

        # 获取草案：优先从缓存取，否则重新生成
        draft = None
        if req.draft_id:
            draft = get_cached_draft(req.draft_id)

        if draft is None:
            connectivity = device_service.analyze_pc_connectivity()
            draft = generate_pc_connectivity_draft(device_service.adapter, connectivity)

        if draft is None:
            return ConfigDeployResultResponse(
                draft_id="",
                success=False,
                device_results=[],
                verification=None,
                deployed_at="",
                error="无需配置：PC1/PC2 连通性已满足",
            )

        # 校验 draft_id（如果提供且缓存未命中导致重新生成）
        if req.draft_id and req.draft_id != draft.draft_id:
            return ConfigDeployResultResponse(
                draft_id=draft.draft_id,
                success=False,
                device_results=[],
                verification=None,
                deployed_at="",
                error=f"draft_id 不匹配：预期 {draft.draft_id}，收到 {req.draft_id}",
            )

        # 执行配置
        result = apply_config_draft(
            draft=draft,
            adapter=device_service.adapter,
            log_service=log_service,
            confirmed=req.confirmed,
        )
        device_service.invalidate_dhcp_cache()

        # 执行后验证（始终尝试，无论 result.success）
        verification = None
        try:
            verification = verify_after_deploy(device_service.adapter)
        except Exception as e:
            log_service.log_config_deploy(
                draft.draft_id,
                success=False,
                detail=f"执行后验证失败: {e}",
            )

        # 最终 success = 命令执行成功 且 验证通过
        final_success = result.success
        if verification is not None:
            if not (verification.pc1_to_pc2_reachable and verification.pc2_to_pc1_reachable):
                final_success = False

        # 存储最近部署结果
        from backend.services.config_deploy_service import _store_deploy_result
        _store_deploy_result(result, verification)

        return ConfigDeployResultResponse(
            draft_id=result.draft_id,
            success=final_success,
            device_results=[
                DeviceDeployResultResponse(
                    device_id=dr.device_id,
                    device_name=dr.device_name,
                    backup_success=dr.backup_success,
                    backup_error=dr.backup_error,
                    command_results=[
                        ConfigCommandResultResponse(
                            command=r.command,
                            success=r.success,
                            output=r.output,
                            error=r.error,
                        )
                        for r in dr.command_results
                    ],
                    all_commands_success=dr.all_commands_success,
                    error=dr.error,
                )
                for dr in result.device_results
            ],
            verification=VerificationResultResponse(
                pc1_to_pc2_reachable=verification.pc1_to_pc2_reachable,
                pc2_to_pc1_reachable=verification.pc2_to_pc1_reachable,
                gaps=verification.gaps,
                verified_at=verification.verified_at,
            ) if verification else None,
            deployed_at=result.deployed_at,
            error=result.error,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"配置下发失败: {e}")


@app.get("/api/analysis/ospf", response_model=OspfAnalysisResponse)
def analyze_ospf():
    """分析 OSPF 配置状态。

    检查每台路由器的 OSPF 邻居状态、路由表中的 OSPF 路由。
    只读操作，不执行任何配置。
    """
    try:
        from backend.services.connectivity_analysis import analyze_ospf_config

        diags = device_service.get_topology_diagnostics()
        result = analyze_ospf_config(diags)

        return OspfAnalysisResponse(
            device_analyses=[
                OspfDeviceAnalysisResponse(
                    device_name=da.device_name,
                    ospf_process_id=da.ospf_process_id,
                    router_id=da.router_id,
                    area=da.area,
                    peers=[
                        OspfPeerResponse(
                            router_id=p.router_id,
                            address=p.address,
                            state=p.state,
                            interface=p.interface,
                        )
                        for p in da.peers
                    ],
                    ospf_routes=[
                        RouteEntryResponse(
                            destination=r.destination,
                            mask=r.mask,
                            proto=r.proto,
                            next_hop=r.next_hop,
                            interface=r.interface,
                        )
                        for r in da.ospf_routes
                    ],
                    interfaces_advertised=da.interfaces_advertised,
                    issues=da.issues,
                )
                for da in result.device_analyses
            ],
            all_peers_full=result.all_peers_full,
            all_networks_advertised=result.all_networks_advertised,
            gaps=result.gaps,
            config_suggestions=result.config_suggestions,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OSPF 分析失败: {e}")


@app.get("/api/config/ospf/preview", response_model=Optional[ConfigDraftResponse])
def ospf_config_preview():
    """获取 OSPF 配置草案预览。

    基于当前 OSPF 分析结果，生成 OSPF 配置草案。
    只读操作，不执行任何配置。所有设备已配置 OSPF 时返回 null。
    """
    try:
        from backend.services.config_deploy_service import generate_ospf_draft

        diags = device_service.get_topology_diagnostics()
        draft = generate_ospf_draft(device_service.adapter, diags)

        if draft is None:
            return None

        log_service.log_config_preview(draft.draft_id, len(draft.devices))

        return ConfigDraftResponse(
            draft_id=draft.draft_id,
            created_at=draft.created_at,
            purpose=draft.purpose,
            devices=[
                ConfigCommandDraftResponse(
                    device_name=d.device_name,
                    commands=d.commands,
                    purpose=d.purpose,
                    risk_level=d.risk_level,
                    risk_warning=d.risk_warning,
                )
                for d in draft.devices
            ],
            risk_summary=draft.risk_summary,
            warnings=draft.warnings,
            requires_confirmation=draft.requires_confirmation,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成 OSPF 配置草案失败: {e}")


@app.post("/api/config/ospf/apply", response_model=ConfigDeployResultResponse)
def ospf_config_apply(req: ConfigApplyRequest):
    """执行 OSPF 配置下发。

    安全条件（必须同时满足）：
    1. 请求体 confirmed=true
    2. ENABLE_REAL_ENSP=true
    3. 仅执行系统生成的 OSPF 草案

    执行流程：
    1. 生成 OSPF 配置草案
    2. 白名单校验所有命令
    3. 每台设备执行前自动备份
    4. 逐设备逐条执行配置命令
    5. 执行后自动验证 PC1/PC2 连通性
    """
    try:
        from backend.services.config_deploy_service import (
            apply_config_draft,
            generate_ospf_draft,
            get_cached_draft,
            verify_after_deploy,
            _store_deploy_result,
        )

        # 检查 ENABLE_REAL_ENSP
        import os
        enable_real = os.getenv("ENABLE_REAL_ENSP", "false").lower() == "true"
        if not enable_real:
            return ConfigDeployResultResponse(
                draft_id="",
                success=False,
                device_results=[],
                verification=None,
                deployed_at="",
                error="ENABLE_REAL_ENSP 未启用，拒绝执行 OSPF 配置下发",
            )

        # 获取草案
        draft = None
        if req.draft_id:
            draft = get_cached_draft(req.draft_id)

        if draft is None:
            diags = device_service.get_topology_diagnostics()
            draft = generate_ospf_draft(device_service.adapter, diags)

        if draft is None:
            return ConfigDeployResultResponse(
                draft_id="",
                success=False,
                device_results=[],
                verification=None,
                deployed_at="",
                error="无需配置：所有设备已配置 OSPF",
            )

        # 校验 draft_id
        if req.draft_id and req.draft_id != draft.draft_id:
            return ConfigDeployResultResponse(
                draft_id=draft.draft_id,
                success=False,
                device_results=[],
                verification=None,
                deployed_at="",
                error=f"draft_id 不匹配：预期 {draft.draft_id}，收到 {req.draft_id}",
            )

        # 执行配置
        result = apply_config_draft(
            draft=draft,
            adapter=device_service.adapter,
            log_service=log_service,
            confirmed=req.confirmed,
        )

        # 执行后验证
        verification = None
        try:
            verification = verify_after_deploy(device_service.adapter)
        except Exception as e:
            log_service.log_config_deploy(
                draft.draft_id,
                success=False,
                detail=f"执行后验证失败: {e}",
            )

        # 最终 success
        final_success = result.success
        if verification is not None:
            if not (verification.pc1_to_pc2_reachable and verification.pc2_to_pc1_reachable):
                final_success = False

        # 存储部署结果
        _store_deploy_result(result, verification)

        return ConfigDeployResultResponse(
            draft_id=result.draft_id,
            success=final_success,
            device_results=[
                DeviceDeployResultResponse(
                    device_id=dr.device_id,
                    device_name=dr.device_name,
                    backup_success=dr.backup_success,
                    backup_error=dr.backup_error,
                    command_results=[
                        ConfigCommandResultResponse(
                            command=r.command,
                            success=r.success,
                            output=r.output,
                            error=r.error,
                        )
                        for r in dr.command_results
                    ],
                    all_commands_success=dr.all_commands_success,
                    error=dr.error,
                )
                for dr in result.device_results
            ],
            verification=VerificationResultResponse(
                pc1_to_pc2_reachable=verification.pc1_to_pc2_reachable,
                pc2_to_pc1_reachable=verification.pc2_to_pc1_reachable,
                gaps=verification.gaps,
                verified_at=verification.verified_at,
            ) if verification else None,
            deployed_at=result.deployed_at,
            error=result.error,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OSPF 配置下发失败: {e}")


@app.get("/api/analysis/vlan", response_model=VlanAnalysisResponse)
def analyze_vlan():
    """分析 VLAN 配置状态。

    检查每台路由器的 VLAN 是否已创建。
    只读操作，不执行任何配置。
    """
    try:
        from backend.services.connectivity_analysis import analyze_vlan_config

        diags = device_service.get_topology_diagnostics()
        result = analyze_vlan_config(diags)

        return VlanAnalysisResponse(
            device_analyses=[
                VlanDeviceAnalysisResponse(
                    device_name=da.device_name,
                    vlans=[
                        VlanEntryResponse(
                            vlan_id=v.vlan_id,
                            vlan_type=v.vlan_type,
                            ports=v.ports,
                        )
                        for v in da.vlans
                    ],
                    issues=da.issues,
                )
                for da in result.device_analyses
            ],
            all_vlans_configured=result.all_vlans_configured,
            all_ports_assigned=result.all_ports_assigned,
            gaps=result.gaps,
            config_suggestions=result.config_suggestions,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"VLAN 分析失败: {e}")


@app.get("/api/config/vlan/preview", response_model=Optional[ConfigDraftResponse])
def vlan_config_preview():
    """获取 VLAN 配置草案预览。

    基于当前 VLAN 分析结果，生成 VLAN 配置草案。
    只读操作，不执行任何配置。所有设备已配置 VLAN 时返回 null。
    """
    try:
        from backend.services.config_deploy_service import generate_vlan_draft

        diags = device_service.get_topology_diagnostics()
        draft = generate_vlan_draft(device_service.adapter, diags)

        if draft is None:
            return None

        log_service.log_config_preview(draft.draft_id, len(draft.devices))

        return ConfigDraftResponse(
            draft_id=draft.draft_id,
            created_at=draft.created_at,
            purpose=draft.purpose,
            devices=[
                ConfigCommandDraftResponse(
                    device_name=d.device_name,
                    commands=d.commands,
                    purpose=d.purpose,
                    risk_level=d.risk_level,
                    risk_warning=d.risk_warning,
                )
                for d in draft.devices
            ],
            risk_summary=draft.risk_summary,
            warnings=draft.warnings,
            requires_confirmation=draft.requires_confirmation,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成 VLAN 配置草案失败: {e}")


@app.post("/api/config/vlan/apply", response_model=ConfigDeployResultResponse)
def vlan_config_apply(req: ConfigApplyRequest):
    """执行 VLAN 配置下发。

    安全条件（必须同时满足）：
    1. 请求体 confirmed=true
    2. ENABLE_REAL_ENSP=true
    3. 仅执行系统生成的 VLAN 草案

    执行流程：
    1. 生成 VLAN 配置草案
    2. 白名单校验所有命令
    3. 每台设备执行前自动备份
    4. 逐设备逐条执行配置命令
    5. 执行后自动验证 PC1/PC2 连通性
    """
    try:
        from backend.services.config_deploy_service import (
            apply_config_draft,
            generate_vlan_draft,
            get_cached_draft,
            verify_after_deploy,
            _store_deploy_result,
        )

        # 检查 ENABLE_REAL_ENSP
        import os
        enable_real = os.getenv("ENABLE_REAL_ENSP", "false").lower() == "true"
        if not enable_real:
            return ConfigDeployResultResponse(
                draft_id="",
                success=False,
                device_results=[],
                verification=None,
                deployed_at="",
                error="ENABLE_REAL_ENSP 未启用，拒绝执行 VLAN 配置下发",
            )

        # 获取草案
        draft = None
        if req.draft_id:
            draft = get_cached_draft(req.draft_id)

        if draft is None:
            diags = device_service.get_topology_diagnostics()
            draft = generate_vlan_draft(device_service.adapter, diags)

        if draft is None:
            return ConfigDeployResultResponse(
                draft_id="",
                success=False,
                device_results=[],
                verification=None,
                deployed_at="",
                error="无需配置：所有设备已配置 VLAN",
            )

        # 校验 draft_id
        if req.draft_id and req.draft_id != draft.draft_id:
            return ConfigDeployResultResponse(
                draft_id=draft.draft_id,
                success=False,
                device_results=[],
                verification=None,
                deployed_at="",
                error=f"draft_id 不匹配：预期 {draft.draft_id}，收到 {req.draft_id}",
            )

        # 执行配置
        result = apply_config_draft(
            draft=draft,
            adapter=device_service.adapter,
            log_service=log_service,
            confirmed=req.confirmed,
        )

        # 执行后验证
        verification = None
        try:
            verification = verify_after_deploy(device_service.adapter)
        except Exception as e:
            log_service.log_config_deploy(
                draft.draft_id,
                success=False,
                detail=f"执行后验证失败: {e}",
            )

        # 最终 success
        final_success = result.success
        if verification is not None:
            if not (verification.pc1_to_pc2_reachable and verification.pc2_to_pc1_reachable):
                final_success = False

        # 存储部署结果
        _store_deploy_result(result, verification)

        return ConfigDeployResultResponse(
            draft_id=result.draft_id,
            success=final_success,
            device_results=[
                DeviceDeployResultResponse(
                    device_id=dr.device_id,
                    device_name=dr.device_name,
                    backup_success=dr.backup_success,
                    backup_error=dr.backup_error,
                    command_results=[
                        ConfigCommandResultResponse(
                            command=r.command,
                            success=r.success,
                            output=r.output,
                            error=r.error,
                        )
                        for r in dr.command_results
                    ],
                    all_commands_success=dr.all_commands_success,
                    error=dr.error,
                )
                for dr in result.device_results
            ],
            verification=VerificationResultResponse(
                pc1_to_pc2_reachable=verification.pc1_to_pc2_reachable,
                pc2_to_pc1_reachable=verification.pc2_to_pc1_reachable,
                gaps=verification.gaps,
                verified_at=verification.verified_at,
            ) if verification else None,
            deployed_at=result.deployed_at,
            error=result.error,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"VLAN 配置下发失败: {e}")


# --- DHCP 分析与配置端点 ---

@app.get("/api/analysis/dhcp", response_model=DhcpAnalysisResponse)
def analyze_dhcp():
    """分析 DHCP 地址分发配置状态。

    检查 LSW1-LSW4 的 VLAN/Vlanif/DHCP/端口配置。
    只读操作，不执行任何配置。
    """
    try:
        from backend.services.dhcp_analysis import analyze_dhcp_config

        diags = device_service.get_topology_diagnostics()
        result = analyze_dhcp_config(diags)

        return DhcpAnalysisResponse(
            device_analyses=[
                DhcpSwitchAnalysisResponse(
                    device_name=da.device_name,
                    device_type=da.device_type,
                    vlans=da.vlans,
                    vlanifs=[
                        VlanifResponse(
                            vlan_id=v.vlan_id,
                            ip_address=v.ip_address,
                            subnet_mask=v.subnet_mask,
                            dhcp_select=v.dhcp_select,
                        )
                        for v in da.vlanifs
                    ],
                    dhcp_enabled=da.dhcp_enabled,
                    dhcp_pools=[
                        DhcpPoolResponse(
                            name=p.name,
                            network=p.network,
                            gateway=p.gateway,
                            mask=p.mask,
                            lease=p.lease,
                        )
                        for p in da.dhcp_pools
                    ],
                    access_ports=da.access_ports,
                    trunk_ports=da.trunk_ports,
                    issues=da.issues,
                )
                for da in result.device_analyses
            ],
            all_vlans_configured=result.all_vlans_configured,
            all_vlanifs_configured=result.all_vlanifs_configured,
            dhcp_fully_configured=result.dhcp_fully_configured,
            all_ports_correct=result.all_ports_correct,
            gaps=result.gaps,
            config_suggestions=result.config_suggestions,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DHCP 分析失败: {e}")


@app.get("/api/config/dhcp/preview", response_model=Optional[ConfigDraftResponse])
def dhcp_config_preview():
    """获取 DHCP 配置草案预览。

    基于当前 DHCP 分析结果，生成 DHCP 配置草案。
    只读操作，不执行任何配置。所有设备已配置 DHCP 时返回 null。
    """
    try:
        from backend.services.config_deploy_service import generate_dhcp_draft

        diags = device_service.get_topology_diagnostics()
        draft = generate_dhcp_draft(device_service.adapter, diags)

        if draft is None:
            return None

        log_service.log_config_preview(draft.draft_id, len(draft.devices))

        return ConfigDraftResponse(
            draft_id=draft.draft_id,
            created_at=draft.created_at,
            purpose=draft.purpose,
            devices=[
                ConfigCommandDraftResponse(
                    device_name=d.device_name,
                    commands=d.commands,
                    purpose=d.purpose,
                    risk_level=d.risk_level,
                    risk_warning=d.risk_warning,
                )
                for d in draft.devices
            ],
            risk_summary=draft.risk_summary,
            warnings=draft.warnings,
            requires_confirmation=draft.requires_confirmation,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成 DHCP 配置草案失败: {e}")


@app.post("/api/config/dhcp/apply", response_model=ConfigDeployResultResponse)
def dhcp_config_apply(req: ConfigApplyRequest):
    """执行 DHCP 配置下发。

    安全条件（必须同时满足）：
    1. 请求体 confirmed=true
    2. ENABLE_REAL_ENSP=true
    3. 仅执行系统生成的 DHCP 草案
    """
    try:
        from backend.services.config_deploy_service import (
            apply_config_draft,
            generate_dhcp_draft,
            get_cached_draft,
        )

        # 检查 ENABLE_REAL_ENSP
        import os
        enable_real = os.getenv("ENABLE_REAL_ENSP", "false").lower() == "true"
        if not enable_real:
            return ConfigDeployResultResponse(
                draft_id="",
                success=False,
                device_results=[],
                verification=None,
                deployed_at="",
                error="ENABLE_REAL_ENSP 未启用，拒绝执行 DHCP 配置下发",
            )

        # 获取草案
        draft = None
        if req.draft_id:
            draft = get_cached_draft(req.draft_id)

        if draft is None:
            diags = device_service.get_topology_diagnostics()
            draft = generate_dhcp_draft(device_service.adapter, diags)

        if draft is None:
            return ConfigDeployResultResponse(
                draft_id="",
                success=False,
                device_results=[],
                verification=None,
                deployed_at="",
                error="无需配置：所有交换机 DHCP 配置已就绪",
            )

        # 校验 draft_id
        if req.draft_id and req.draft_id != draft.draft_id:
            return ConfigDeployResultResponse(
                draft_id=draft.draft_id,
                success=False,
                device_results=[],
                verification=None,
                deployed_at="",
                error=f"draft_id 不匹配：预期 {draft.draft_id}，收到 {req.draft_id}",
            )

        # 执行配置
        result = apply_config_draft(
            draft=draft,
            adapter=device_service.adapter,
            log_service=log_service,
            confirmed=req.confirmed,
        )

        # 标记 DHCP 已应用（切换 mock 状态）
        if result.success:
            try:
                from backend.adapters.mock_adapter import set_dhcp_applied
                set_dhcp_applied()
            except ImportError:
                pass

        # 存储部署结果
        from backend.services.config_deploy_service import _store_deploy_result
        _store_deploy_result(result, None)

        return ConfigDeployResultResponse(
            draft_id=result.draft_id,
            success=result.success,
            device_results=[
                DeviceDeployResultResponse(
                    device_id=dr.device_id,
                    device_name=dr.device_name,
                    backup_success=dr.backup_success,
                    backup_error=dr.backup_error,
                    command_results=[
                        ConfigCommandResultResponse(
                            command=r.command,
                            success=r.success,
                            output=r.output,
                            error=r.error,
                        )
                        for r in dr.command_results
                    ],
                    all_commands_success=dr.all_commands_success,
                    error=dr.error,
                )
                for dr in result.device_results
            ],
            verification=None,
            deployed_at=result.deployed_at,
            error=result.error,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DHCP 配置下发失败: {e}")


@app.get("/api/config/save/preview", response_model=Optional[list[str]])
def save_preview():
    """获取 save 预览：返回需要执行 save 的路由器列表。

    前置条件：final-report 视角下已经 success（health ready + 双向可达 + 部署成功）。
    不满足时返回 null。只读操作，不执行 save。
    """
    try:
        from backend.services.config_deploy_service import check_final_success

        check = check_final_success(device_service.adapter)
        if not check.is_success:
            return None

        device_names: list[str] = []
        for device in device_service.adapter.list_devices():
            if device.type in {"router", "switch"}:
                device_names.append(device.name)
        return sorted(device_names)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成 save 预览失败: {e}")


@app.post("/api/config/save/apply", response_model=SaveAllResultResponse)
def save_apply(req: SaveApplyRequest):
    """对所有路由器执行 save 命令，持久化当前配置。

    安全条件（必须同时满足）：
    1. 请求体 confirmed=true
    2. ENABLE_REAL_ENSP=true
    3. final-report 视角下已经 success

    不满足前两条时直接拒绝，不写入 save 缓存。
    不满足第三条时拒绝，不写入 save 缓存。
    """
    try:
        import os
        from backend.services.config_deploy_service import (
            save_all_configs,
            _store_save_result,
            check_final_success,
        )

        # 检查 ENABLE_REAL_ENSP（未启用 → 拒绝，不写缓存）
        enable_real = os.getenv("ENABLE_REAL_ENSP", "false").lower() == "true"
        if not enable_real:
            return SaveAllResultResponse(
                success=False,
                device_results=[],
                saved_at="",
                error="ENABLE_REAL_ENSP 未启用，拒绝执行 save",
            )

        # 检查 confirmed（未确认 → 拒绝，不写缓存）
        if not req.confirmed:
            return SaveAllResultResponse(
                success=False,
                device_results=[],
                saved_at="",
                error="未确认：save 需要显式传入 confirmed=true",
            )

        # 检查 final-report 视角的 success（不满足 → 拒绝，不写缓存）
        check = check_final_success(device_service.adapter)
        if not check.is_success:
            return SaveAllResultResponse(
                success=False,
                device_results=[],
                saved_at="",
                error=f"前置条件不满足：{check.reason}",
            )

        # 全部前置条件满足，执行 save
        result = save_all_configs(
            adapter=device_service.adapter,
            log_service=log_service,
        )

        # 仅真正执行后才写入缓存
        _store_save_result(result)

        return SaveAllResultResponse(
            success=result.success,
            device_results=[
                DeviceSaveResultResponse(
                    device_id=dr.device_id,
                    device_name=dr.device_name,
                    success=dr.success,
                    output=dr.output,
                    error=dr.error,
                )
                for dr in result.device_results
            ],
            saved_at=result.saved_at,
            error=result.error,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"save 执行失败: {e}")


@app.get("/api/config/rollback/preview", response_model=RollbackPreviewResponse)
def rollback_preview():
    """获取回滚预览：检查是否存在可用于回滚的最近部署备份。

    只读操作，不执行回滚。
    """
    try:
        from backend.services.config_rollback_service import get_rollback_preview

        preview = get_rollback_preview(device_service.adapter)
        return RollbackPreviewResponse(
            available=preview.available,
            devices=[
                DeviceRollbackInfoResponse(
                    device_id=d.device_id,
                    device_name=d.device_name,
                    backup_path=d.backup_path,
                    has_backup=d.has_backup,
                )
                for d in preview.devices
            ],
            warnings=preview.warnings,
            requires_confirmation=preview.requires_confirmation,
            reason=preview.reason,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成回滚预览失败: {e}")


@app.post("/api/config/rollback/apply", response_model=RollbackResultResponse)
def rollback_apply(req: RollbackApplyRequest):
    """执行配置回滚：基于最近一次部署前备份恢复设备配置。

    安全条件（必须同时满足）：
    1. 请求体 confirmed=true
    2. ENABLE_REAL_ENSP=true
    3. 存在最近一次部署且备份完整
    """
    try:
        import os
        from backend.services.config_rollback_service import (
            apply_rollback,
            get_rollback_preview,
            _store_rollback_result,
        )

        # 检查 ENABLE_REAL_ENSP（未启用 → 拒绝，不写缓存）
        enable_real = os.getenv("ENABLE_REAL_ENSP", "false").lower() == "true"
        if not enable_real:
            return RollbackResultResponse(
                success=False,
                device_results=[],
                verification=None,
                rolled_back_at="",
                error="ENABLE_REAL_ENSP 未启用，拒绝执行回滚",
            )

        # 检查 confirmed（未确认 → 拒绝，不写缓存）
        if not req.confirmed:
            return RollbackResultResponse(
                success=False,
                device_results=[],
                verification=None,
                rolled_back_at="",
                error="未确认：回滚需要显式传入 confirmed=true",
            )

        # 检查是否存在可回滚内容（不可用 → 拒绝，不写缓存）
        preview = get_rollback_preview(device_service.adapter)
        if not preview.available:
            return RollbackResultResponse(
                success=False,
                device_results=[],
                verification=None,
                rolled_back_at="",
                error=f"无可用回滚内容：{preview.reason}",
            )

        # 执行回滚
        result = apply_rollback(
            adapter=device_service.adapter,
            log_service=log_service,
            confirmed=req.confirmed,
        )
        device_service.invalidate_dhcp_cache()

        # 仅真正执行后才写入缓存
        _store_rollback_result(result)

        return RollbackResultResponse(
            success=result.success,
            device_results=[
                DeviceRollbackResultResponse(
                    device_id=dr.device_id,
                    device_name=dr.device_name,
                    success=dr.success,
                    output=dr.output,
                    error=dr.error,
                    error_code=dr.error_code,
                    recovery_hint=dr.recovery_hint,
                    manual_steps=dr.manual_steps,
                    backup_path=dr.backup_path,
                )
                for dr in result.device_results
            ],
            verification=VerificationResultResponse(
                pc1_to_pc2_reachable=result.verification.pc1_to_pc2_reachable,
                pc2_to_pc1_reachable=result.verification.pc2_to_pc1_reachable,
                gaps=result.verification.gaps,
                verified_at=result.verification.verified_at,
            ) if result.verification else None,
            rolled_back_at=result.rolled_back_at,
            error=result.error,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"回滚执行失败: {e}")


@app.get("/api/verification/final-report", response_model=FinalReportResponse)
def final_report():
    """获取最终验证报告。

    汇总环境健康、设备诊断、连通性分析、最近部署结果，
    给出最终验证结论和建议下一步。
    """
    try:
        from backend.services.config_deploy_service import (
            get_latest_deploy,
            get_latest_verification,
            get_latest_save,
            check_final_success,
        )
        from backend.services.config_rollback_service import get_latest_rollback

        # 1-3. 复用 check_final_success() 作为 success 判定基础
        #      内部已完成 health check、诊断、连通性分析、deploy 检查
        check = check_final_success(device_service.adapter)

        # 4. 构建响应所需的明细数据（独立获取，不依赖 check 内部状态）
        from backend.services.device_service import check_ensp_health
        health = check_ensp_health()

        diags = device_service.get_topology_diagnostics()

        from backend.services.connectivity_analysis import analyze_pc_connectivity
        connectivity = analyze_pc_connectivity(diags)

        latest_deploy_raw = get_latest_deploy()
        latest_verification = get_latest_verification()
        latest_deploy_resp = None

        if latest_deploy_raw is not None:
            dep = latest_deploy_raw
            ver = latest_verification
            latest_deploy_resp = LatestDeploySummaryResponse(
                draft_id=dep.draft_id,
                deployed_at=dep.deployed_at,
                device_count=len(dep.device_results),
                all_backup_success=all(dr.backup_success for dr in dep.device_results),
                all_commands_success=dep.success,
                overall_success=dep.success,
                verification_passed=(
                    ver.pc1_to_pc2_reachable and ver.pc2_to_pc1_reachable
                ) if ver else None,
                device_names=[dr.device_name for dr in dep.device_results],
            )

        # 5. 最终状态判定（基于 check_final_success() 的字段，保持细分状态）
        if not check.health_ready:
            final_status = "failed"
        elif not check.deploy_ok:
            final_status = "failed"
        elif check.is_success:
            final_status = "success"
        elif latest_deploy_raw is None and connectivity.gaps:
            final_status = "not_executed"
        elif connectivity.gaps:
            final_status = "partial"
        else:
            final_status = "partial"

        # 5.5 save 状态
        latest_save = get_latest_save()
        if latest_save is None:
            save_status = "未执行save"
        elif latest_save.success:
            save_status = "save成功"
        else:
            save_status = "save失败"

        # 5.6 rollback 状态
        latest_rollback = get_latest_rollback()
        if latest_rollback is None:
            rollback_status = "未执行rollback"
        elif latest_rollback.success:
            rollback_status = "rollback成功"
        else:
            rollback_status = "rollback失败"

        # 6. 摘要
        if final_status == "success":
            summary = "PC1 与 PC2 已具备双向互通条件，验证通过。"
        elif final_status == "not_executed":
            summary = "尚未执行配置下发，PC1/PC2 互通条件未满足。"
        elif final_status == "failed":
            reasons = []
            if not check.health_ready:
                reasons.append("环境健康检查未通过")
            if not check.deploy_ok:
                reasons.append("最近一次配置执行失败")
            summary = f"验证未通过：{'；'.join(reasons)}。"
        else:
            summary = f"部分满足，仍存在缺口：{'; '.join(connectivity.gaps)}。"

        if latest_save is not None:
            if latest_save.success:
                summary += " 配置已持久化保存。"
            else:
                summary += " 配置保存失败。"

        # 7. 建议下一步
        next_steps: list[str] = []
        if not check.health_ready:
            next_steps.append("修复环境健康检查问题（见 health.issues）")
        elif final_status == "success":
            if latest_save is None:
                next_steps.append("PC1 与 PC2 已具备互通条件，执行 POST /api/config/save/apply 持久化配置")
            elif latest_save.success:
                next_steps.append("验证完成，配置已持久化保存到设备")
            else:
                next_steps.append("配置保存失败，检查设备连接后重试 POST /api/config/save/apply")
        elif final_status == "not_executed":
            next_steps.append("先执行 GET /api/config/pc-connectivity/preview 预览配置草案")
            next_steps.append("确认后执行 POST /api/config/pc-connectivity/apply 下发静态路由")
        elif final_status == "failed":
            if not check.deploy_ok:
                next_steps.append("检查最近一次配置执行失败原因（见 latest_deploy）")
            next_steps.append("重新执行配置下发或手动排查设备连接问题")
        else:
            if connectivity.gaps:
                next_steps.append(f"补齐缺口：{'; '.join(connectivity.gaps[:3])}")
            next_steps.append("重新执行配置下发并验证")

        return FinalReportResponse(
            health=EnspHealthReportResponse(
                enabled=health.enabled,
                devices=[
                    DeviceHealthCheckResponse(
                        device_name=d.device_name,
                        host_configured=d.host_configured,
                        port_configured=d.port_configured,
                        credential_env_exists=d.credential_env_exists,
                        issues=d.issues,
                    )
                    for d in health.devices
                ],
                ready=health.ready,
                issues=health.issues,
            ),
            diagnostics=[
                DeviceDiagnosticsResponse(
                    device_id=d.device_id,
                    device_name=d.device_name,
                    collected_at=d.collected_at,
                    commands=[
                        CommandOutputResponse(
                            command=c.command,
                            success=c.success,
                            output=c.output,
                            error=c.error,
                        )
                        for c in d.commands
                    ],
                )
                for d in diags
            ],
            connectivity=_to_connectivity_response(connectivity),
            latest_deploy=latest_deploy_resp,
            save_status=save_status,
            rollback_status=rollback_status,
            final_status=final_status,
            summary=summary,
            next_steps=next_steps,
            generated_at=datetime.now().isoformat(),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成最终验证报告失败: {e}")


@app.get("/api/verification/dhcp-final", response_model=DhcpFinalReportResponse)
def get_dhcp_final_report():
    """获取 DHCP 最终验证报告。

    验证 PC4/5/6 是否通过 DHCP 获取到正确地址。
    Mock 模式下完整验证；真实 eNSP 下标注"PC 侧自动读取待后续实现"。
    """
    try:
        from backend.services.dhcp_verification_service import verify_dhcp_result

        adapter = device_service.adapter
        diags = device_service.get_topology_diagnostics()
        report = verify_dhcp_result(adapter, diags)

        return DhcpFinalReportResponse(
            available=report.available,
            verification_mode=report.verification_mode,
            pc_results=[
                PcDhcpVerificationResponse(
                    pc_name=r.pc_name,
                    expected_vlan=r.expected_vlan,
                    expected_subnet=r.expected_subnet,
                    expected_mask=r.expected_mask,
                    expected_gateway=r.expected_gateway,
                    actual_ip=r.actual_ip,
                    actual_mask=r.actual_mask,
                    actual_gateway=r.actual_gateway,
                    ip_in_expected_subnet=r.ip_in_expected_subnet,
                    mask_ok=r.mask_ok,
                    gateway_ok=r.gateway_ok,
                    dhcp_enabled=r.dhcp_enabled,
                    status=r.status,
                )
                for r in report.pc_results
            ],
            all_success=report.all_success,
            summary=report.summary,
            note=report.note,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成 DHCP 最终验证报告失败: {e}")


@app.get("/api/logs", response_model=list[LogEntryResponse])
def get_logs(
    limit: int = 100,
    level: Optional[str] = None,
    action: Optional[str] = None,
    device_id: Optional[str] = None,
):
    """查询操作日志。"""
    log_level = None
    log_action = None

    if level:
        try:
            log_level = LogLevel(level)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"无效的日志级别: {level}，可选: {[e.value for e in LogLevel]}",
            )

    if action:
        try:
            log_action = LogAction(action)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"无效的操作类型: {action}，可选: {[e.value for e in LogAction]}",
            )

    entries = log_service.get_logs(
        limit=limit,
        level=log_level,
        action=log_action,
        device_id=device_id,
    )

    return [
        LogEntryResponse(
            id=e.id,
            timestamp=e.timestamp,
            level=e.level.value,
            action=e.action.value,
            device_id=e.device_id,
            device_name=e.device_name,
            command=e.command,
            detail=e.detail,
            success=e.success,
        )
        for e in entries
    ]


def _to_diagnostics_response(diag: DeviceDiagnostics) -> DeviceDiagnosticsResponse:
    """将 DeviceDiagnostics 转换为响应模型。"""
    return DeviceDiagnosticsResponse(
        device_id=diag.device_id,
        device_name=diag.device_name,
        collected_at=diag.collected_at,
        commands=[
            CommandOutputResponse(
                command=c.command,
                success=c.success,
                output=c.output,
                error=c.error,
            )
            for c in diag.commands
        ],
    )


def _to_verification_response(summary) -> VerificationSummaryResponse:
    """将 VerificationSummary 转换为响应模型。"""
    return VerificationSummaryResponse(
        health=EnspHealthReportResponse(
            enabled=summary.health.enabled,
            devices=[
                DeviceHealthCheckResponse(
                    device_name=d.device_name,
                    host_configured=d.host_configured,
                    port_configured=d.port_configured,
                    credential_env_exists=d.credential_env_exists,
                    issues=d.issues,
                )
                for d in summary.health.devices
            ],
            ready=summary.health.ready,
            issues=summary.health.issues,
        ),
        device_diagnostics=[
            DeviceDiagSummaryResponse(
                device_name=d.device_name,
                commands_collected=d.commands_collected,
                commands_failed=d.commands_failed,
                failed_commands=d.failed_commands,
            )
            for d in summary.device_diagnostics
        ],
        successful_devices=summary.successful_devices,
        failed_devices=summary.failed_devices,
        connectivity=_to_connectivity_response(summary.connectivity),
        next_steps=summary.next_steps,
    )


def _to_connectivity_response(result) -> ConnectivityAnalysisResponse:
    """将 ConnectivityAnalysis 转换为响应模型。"""
    from backend.services.connectivity_analysis import ConnectivityAnalysis

    device_analyses = []
    for da in result.device_analyses:
        device_analyses.append(DeviceAnalysisResponse(
            device_name=da.device_name,
            interfaces=[
                InterfaceStatusResponse(
                    name=i.name,
                    phy_up=i.phy_up,
                    protocol_up=i.protocol_up,
                    ip_address=i.ip_address,
                    status=i.status,
                )
                for i in da.interfaces
            ],
            routes=[
                RouteEntryResponse(
                    destination=r.destination,
                    mask=r.mask,
                    proto=r.proto,
                    next_hop=r.next_hop,
                    interface=r.interface,
                )
                for r in da.routes
            ],
            issues=da.issues,
        ))

    return ConnectivityAnalysisResponse(
        pc1_network=result.pc1_network,
        pc2_network=result.pc2_network,
        path=result.path,
        device_analyses=device_analyses,
        pc1_to_pc2_reachable=result.pc1_to_pc2_reachable,
        pc2_to_pc1_reachable=result.pc2_to_pc1_reachable,
        gaps=result.gaps,
        config_suggestions=result.config_suggestions,
    )


# --- 自然语言配置助手 ---

@app.post("/api/nl/plan", response_model=NlPlanResponseModel)
def nl_plan(req: NlPlanRequest):
    """根据自然语言需求生成配置计划。"""
    try:
        from backend.services.nl_intent_service import generate_nl_plan

        adapter = device_service.adapter
        diags = device_service.get_topology_diagnostics()
        result = generate_nl_plan(req.request, adapter, diags)

        # 转换 draft dict → Pydantic 模型
        draft_model = None
        if result.draft:
            devices = [
                NlDeviceDraftResponse(**d) for d in result.draft.get("devices", [])
            ]
            draft_model = NlDraftResponse(
                draft_id=result.draft["draft_id"],
                created_at=result.draft["created_at"],
                purpose=result.draft["purpose"],
                risk_summary=result.draft["risk_summary"],
                warnings=result.draft["warnings"],
                requires_confirmation=result.draft["requires_confirmation"],
                devices=devices,
            )

        return NlPlanResponseModel(
            user_request=result.user_request,
            intent_type=result.intent_type,
            supported=result.supported,
            summary=result.summary,
            target_devices=result.target_devices,
            draft_type=result.draft_type,
            confidence=result.confidence,
            draft=draft_model,
            warnings=result.warnings,
            next_action=result.next_action,
            reason=result.reason,
            error_message=result.error_message,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"自然语言解析失败: {e}")
