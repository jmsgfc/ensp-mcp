"""配置下发服务。

职责：
1. 生成 PC1/PC2 互通的静态路由配置草案
2. 生成 OSPF 配置草案（area 0）
3. 生成 VLAN 配置草案（vlan 10 / access 端口）
4. 生成 DHCP 地址分发配置草案（LSW1-LSW4）
5. 提供配置预览（只读）
6. 执行受控配置下发（带安全校验、备份、日志）
7. 执行后验证

安全约束：
- 仅支持系统内部生成的静态路由、OSPF、VLAN 和 DHCP 命令
- 不暴露通用配置执行能力
- 每次执行前必须备份
- 必须显式确认
"""

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from backend.adapters.base_adapter import (
    BaseAdapter,
    ConfigCommandResult,
    DeviceConnectionError,
    DeviceNotFoundError,
    SaveResult,
)
from backend.services.connectivity_analysis import (
    ConnectivityAnalysis,
    OspfAnalysis,
    VlanAnalysis,
    analyze_ospf_config,
    analyze_pc_connectivity,
    analyze_vlan_config,
)
from backend.services.log_service import LogService


# --- 安全白名单 ---

# 允许的静态路由命令模式（正则）
# 格式: ip route-static <dest> <mask> <next-hop>
_STATIC_ROUTE_RE = re.compile(
    r"^ip route-static \d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3} "
    r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3} "
    r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$"
)

# OSPF 精确白名单：仅允许当前拓扑实际会生成的命令
# 由 _OSPF_CONFIGS 在模块加载时构建，不使用宽松正则


def _build_allowed_commands() -> set[str]:
    """从 _OSPF_CONFIGS 构建 OSPF 精确白名单。"""
    allowed: set[str] = set()
    for cfg in _OSPF_CONFIGS:
        for cmd in cfg["commands"]:
            allowed.add(cmd)
    return allowed


def _validate_command(command: str) -> bool:
    """校验单条配置命令是否在白名单内。

    支持：
    - 静态路由: ip route-static <dest> <mask> <next-hop>（正则匹配）
    - OSPF 命令: 仅允许 _OSPF_CONFIGS 中定义的精确命令集合
    - VLAN 命令: 仅允许 _VLAN_CONFIGS 中定义的精确命令集合
    - DHCP 命令: 仅允许 _DHCP_CONFIGS 中定义的精确命令集合
    """
    cmd = command.strip()
    if bool(_STATIC_ROUTE_RE.match(cmd)):
        return True
    if cmd in _ALLOWED_OSPF_COMMANDS:
        return True
    if cmd in _ALLOWED_VLAN_COMMANDS:
        return True
    return cmd in _ALLOWED_DHCP_COMMANDS


# --- 数据模型 ---

@dataclass
class DeviceConfigDraft:
    """单台设备的配置草案。"""
    device_id: str
    device_name: str
    commands: list[str]
    purpose: str
    risk_level: str
    risk_warning: str
    requires_confirmation: bool = True
    needs_backup: bool = True


@dataclass
class ConfigDraft:
    """完整的配置草案。"""
    draft_id: str
    created_at: str
    purpose: str
    devices: list[DeviceConfigDraft]
    risk_summary: str
    warnings: list[str]
    requires_confirmation: bool = True


@dataclass
class DeviceDeployResult:
    """单台设备的执行结果。"""
    device_id: str
    device_name: str
    backup_success: bool
    backup_error: Optional[str]
    command_results: list[ConfigCommandResult]
    all_commands_success: bool
    backup_path: Optional[str] = None
    error: Optional[str] = None


@dataclass
class VerificationResult:
    """执行后验证结果。"""
    pc1_to_pc2_reachable: bool
    pc2_to_pc1_reachable: bool
    gaps: list[str]
    verified_at: str


@dataclass
class DeployResult:
    """完整的执行结果。"""
    draft_id: str
    success: bool
    device_results: list[DeviceDeployResult]
    verification: Optional[VerificationResult]
    deployed_at: str
    error: Optional[str] = None


@dataclass
class DeviceSaveResult:
    """单台设备的保存结果。"""
    device_id: str
    device_name: str
    success: bool
    output: Optional[str] = None
    error: Optional[str] = None


@dataclass
class SaveAllResult:
    """批量保存结果。"""
    success: bool
    device_results: list[DeviceSaveResult]
    saved_at: str
    error: Optional[str] = None


# --- 草案缓存 ---

_draft_cache: dict[str, ConfigDraft] = {}


def get_cached_draft(draft_id: str) -> Optional[ConfigDraft]:
    """从缓存中获取草案。"""
    return _draft_cache.get(draft_id)


def clear_draft_cache() -> None:
    """清空草案缓存（用于测试隔离）。"""
    _draft_cache.clear()


# --- 最近部署结果缓存 ---

_latest_deploy_result: Optional[DeployResult] = None
_latest_verification: Optional[VerificationResult] = None


def get_latest_deploy() -> Optional[DeployResult]:
    """获取最近一次部署结果。"""
    return _latest_deploy_result


def get_latest_verification() -> Optional[VerificationResult]:
    """获取最近一次验证结果。"""
    return _latest_verification


def _store_deploy_result(result: DeployResult, verification: Optional[VerificationResult]) -> None:
    """存储部署和验证结果（内部调用）。"""
    global _latest_deploy_result, _latest_verification
    _latest_deploy_result = result
    _latest_verification = verification


def clear_deploy_cache() -> None:
    """清空部署缓存（用于测试隔离）。"""
    global _latest_deploy_result, _latest_verification
    _latest_deploy_result = None
    _latest_verification = None


# --- 保存结果缓存 ---

_latest_save_result: Optional[SaveAllResult] = None


def get_latest_save() -> Optional[SaveAllResult]:
    """获取最近一次保存结果。"""
    return _latest_save_result


def _store_save_result(result: SaveAllResult) -> None:
    """存储保存结果（内部调用）。"""
    global _latest_save_result
    _latest_save_result = result


def clear_save_cache() -> None:
    """清空保存缓存（用于测试隔离）。"""
    global _latest_save_result
    _latest_save_result = None


# --- 静态路由草案生成 ---

# PC1/PC2 互通所需的静态路由
_STATIC_ROUTES: list[dict] = [
    {
        "device": "AR1",
        "command": "ip route-static 192.168.2.0 255.255.255.0 10.0.12.2",
        "purpose": "AR1 到 PC1 网段 (192.168.2.0/24)，下一跳 AR2 (10.0.12.2)",
    },
    {
        "device": "AR1",
        "command": "ip route-static 192.168.3.0 255.255.255.0 10.0.13.2",
        "purpose": "AR1 到 PC2 网段 (192.168.3.0/24)，下一跳 AR3 (10.0.13.2)",
    },
    {
        "device": "AR2",
        "command": "ip route-static 192.168.3.0 255.255.255.0 10.0.12.1",
        "purpose": "AR2 到 PC2 网段 (192.168.3.0/24)，下一跳 AR1 (10.0.12.1)",
    },
    {
        "device": "AR3",
        "command": "ip route-static 192.168.2.0 255.255.255.0 10.0.13.1",
        "purpose": "AR3 到 PC1 网段 (192.168.2.0/24)，下一跳 AR1 (10.0.13.1)",
    },
]


def _find_device_id_by_name(adapter: BaseAdapter, name: str) -> Optional[str]:
    """根据设备名查找设备 ID。"""
    for d in adapter.list_devices():
        if d.name == name:
            return d.id
    return None


def generate_pc_connectivity_draft(
    adapter: BaseAdapter,
    connectivity: ConnectivityAnalysis,
) -> Optional[ConfigDraft]:
    """基于连通性分析结果生成静态路由配置草案。

    仅当存在路由缺口时才生成草案。
    已有路由的设备不会重复配置。
    """
    # 收集需要配置的路由（排除已有路由的设备）
    needed_routes: list[dict] = []
    for route in _STATIC_ROUTES:
        device_name = route["device"]
        # 从分析结果中查找该设备的路由表
        device_analysis = None
        for da in connectivity.device_analyses:
            if da.device_name == device_name:
                device_analysis = da
                break

        # 如果找不到设备分析或设备在 gaps 中提到缺少路由，则需要配置
        command = route["command"]
        # 从命令中提取目标网段
        parts = command.split()
        dest = parts[2] if len(parts) >= 3 else ""

        needs_route = False
        if device_analysis:
            has_route = any(r.destination == dest for r in device_analysis.routes)
            if not has_route:
                needs_route = True
        else:
            # 没有诊断数据，保守地认为需要配置
            needs_route = True

        if needs_route:
            needed_routes.append(route)

    if not needed_routes:
        return None

    # 按设备分组
    by_device: dict[str, list[dict]] = {}
    for route in needed_routes:
        by_device.setdefault(route["device"], []).append(route)

    # 构建设备草案
    devices: list[DeviceConfigDraft] = []
    for device_name, routes in by_device.items():
        device_id = _find_device_id_by_name(adapter, device_name)
        if not device_id:
            continue

        commands = [r["command"] for r in routes]
        purposes = [r["purpose"] for r in routes]

        devices.append(DeviceConfigDraft(
            device_id=device_id,
            device_name=device_name,
            commands=commands,
            purpose="; ".join(purposes),
            risk_level="low",
            risk_warning="静态路由配置，不影响现有路由协议，仅添加缺失路由",
        ))

    if not devices:
        return None

    # 稳定 draft_id：基于设备+命令内容哈希，不依赖时间戳
    content_parts = []
    for d in devices:
        for cmd in d.commands:
            content_parts.append(f"{d.device_name}:{cmd}")
    content_hash = hashlib.sha256(
        "|".join(sorted(content_parts)).encode()
    ).hexdigest()[:12]
    draft_id = f"static-route-{content_hash}"

    # 检查缓存，避免重复生成
    cached = _draft_cache.get(draft_id)
    if cached is not None:
        return cached

    warnings = [
        "本草案仅包含静态路由命令，用于补齐 PC1/PC2 互通缺失的路由",
        "配置前将自动备份每台设备的当前配置",
        "配置执行后将自动验证 PC1/PC2 连通性",
    ]

    draft = ConfigDraft(
        draft_id=draft_id,
        created_at=datetime.now().isoformat(),
        purpose="补齐 PC1/PC2 互通缺失的静态路由",
        devices=devices,
        risk_summary="低风险：仅添加静态路由，不修改现有配置",
        warnings=warnings,
        requires_confirmation=True,
    )

    # 写入缓存
    _draft_cache[draft_id] = draft
    return draft


# --- OSPF 草案生成 ---

# 每台设备的 OSPF 配置序列（process 1, area 0）
_OSPF_CONFIGS: list[dict] = [
    {
        "device": "AR1",
        "commands": [
            "ospf 1",
            "area 0",
            "network 192.168.1.0 0.0.0.255",
            "network 10.0.12.0 0.0.0.255",
            "network 10.0.13.0 0.0.0.255",
        ],
        "networks": ["192.168.1.0", "10.0.12.0", "10.0.13.0"],
    },
    {
        "device": "AR2",
        "commands": [
            "ospf 1",
            "area 0",
            "network 192.168.2.0 0.0.0.255",
            "network 10.0.12.0 0.0.0.255",
        ],
        "networks": ["192.168.2.0", "10.0.12.0"],
    },
    {
        "device": "AR3",
        "commands": [
            "ospf 1",
            "area 0",
            "network 192.168.3.0 0.0.0.255",
            "network 10.0.13.0 0.0.0.255",
        ],
        "networks": ["192.168.3.0", "10.0.13.0"],
    },
]

# 模块加载时构建 OSPF 精确白名单
_ALLOWED_OSPF_COMMANDS = _build_allowed_commands()


# --- VLAN 草案生成 ---

_VLAN_CONFIGS: list[dict] = [
    {
        "device": "AR1",
        "commands": [
            "vlan 10",
            "port GigabitEthernet0/0/0",
        ],
    },
    {
        "device": "AR2",
        "commands": [
            "vlan 10",
            "port GigabitEthernet0/0/0",
        ],
    },
    {
        "device": "AR3",
        "commands": [
            "vlan 10",
            "port GigabitEthernet0/0/0",
        ],
    },
]


def _build_allowed_vlan_commands() -> set[str]:
    """从 _VLAN_CONFIGS 构建 VLAN 精确白名单。"""
    allowed: set[str] = set()
    for cfg in _VLAN_CONFIGS:
        for cmd in cfg["commands"]:
            allowed.add(cmd)
    return allowed


_ALLOWED_VLAN_COMMANDS = _build_allowed_vlan_commands()


# --- DHCP 草案生成 ---

# 每台设备的 DHCP 配置序列（精确命令集）
_DHCP_CONFIGS: list[dict] = [
    {
        "device": "LSW1",
        "commands": [
            "vlan batch 10 20 30 40",
            "dhcp enable",
            "interface Vlanif10",
            "ip address 192.168.10.1 255.255.255.0",
            "dhcp select global",
            "interface Vlanif20",
            "ip address 192.168.20.1 255.255.255.0",
            "dhcp select global",
            "interface Vlanif30",
            "ip address 192.168.30.1 255.255.255.0",
            "dhcp select global",
            "interface Vlanif40",
            "ip address 192.168.40.1 255.255.255.0",
            "dhcp select global",
            "ip pool vlan10",
            "network 192.168.10.0 mask 255.255.255.0",
            "gateway-list 192.168.10.1",
            "ip pool vlan20",
            "network 192.168.20.0 mask 255.255.255.0",
            "gateway-list 192.168.20.1",
            "ip pool vlan30",
            "network 192.168.30.0 mask 255.255.255.0",
            "gateway-list 192.168.30.1",
            "ip pool vlan40",
            "network 192.168.40.0 mask 255.255.255.0",
            "gateway-list 192.168.40.1",
            "interface GigabitEthernet0/0/1",
            "port link-type trunk",
            "port trunk allow-pass vlan 10 20 30 40",
            "interface GigabitEthernet0/0/2",
            "port link-type trunk",
            "port trunk allow-pass vlan 10 20 30 40",
        ],
    },
    {
        "device": "LSW6",
        "commands": [
            "vlan batch 10 20 30 40",
            "interface Ethernet0/0/1",
            "port link-type trunk",
            "port trunk allow-pass vlan 10 20 30 40",
            "interface Ethernet0/0/2",
            "port link-type trunk",
            "port trunk allow-pass vlan 10 20 30 40",
            "interface Ethernet0/0/3",
            "port link-type trunk",
            "port trunk allow-pass vlan 10 20 30 40",
        ],
    },
    {
        "device": "LSW7",
        "commands": [
            "vlan batch 10 20 30 40",
            "interface Ethernet0/0/1",
            "port link-type trunk",
            "port trunk allow-pass vlan 10 20 30 40",
            "interface Ethernet0/0/2",
            "port link-type trunk",
            "port trunk allow-pass vlan 10 20 30 40",
            "interface Ethernet0/0/3",
            "port link-type trunk",
            "port trunk allow-pass vlan 10 20 30 40",
        ],
    },
    {
        "device": "LSW5",
        "commands": [
            "vlan batch 10",
            "interface Ethernet0/0/1",
            "port link-type trunk",
            "port trunk allow-pass vlan 10 20 30 40",
            "interface Ethernet0/0/2",
            "port link-type access",
            "port default vlan 10",
        ],
    },
    {
        "device": "LSW2",
        "commands": [
            "vlan batch 20",
            "interface Ethernet0/0/1",
            "port link-type trunk",
            "port trunk allow-pass vlan 10 20 30 40",
            "interface Ethernet0/0/2",
            "port link-type access",
            "port default vlan 20",
        ],
    },
    {
        "device": "LSW3",
        "commands": [
            "vlan batch 30",
            "interface Ethernet0/0/1",
            "port link-type trunk",
            "port trunk allow-pass vlan 10 20 30 40",
            "interface Ethernet0/0/2",
            "port link-type access",
            "port default vlan 30",
        ],
    },
    {
        "device": "LSW4",
        "commands": [
            "vlan batch 40",
            "interface Ethernet0/0/2",
            "port link-type access",
            "port default vlan 40",
            "interface Ethernet0/0/3",
            "port link-type trunk",
            "port trunk allow-pass vlan 10 20 30 40",
        ],
    },
]


def _build_allowed_dhcp_commands() -> set[str]:
    """从 _DHCP_CONFIGS 构建 DHCP 精确白名单。"""
    allowed: set[str] = set()
    for cfg in _DHCP_CONFIGS:
        for cmd in cfg["commands"]:
            allowed.add(cmd)
    return allowed


_ALLOWED_DHCP_COMMANDS = _build_allowed_dhcp_commands()


def generate_ospf_draft(
    adapter: BaseAdapter,
    diagnostics: list,
) -> Optional[ConfigDraft]:
    """基于 OSPF 分析结果生成 OSPF 配置草案。

    判定逻辑（三层）：
    1. 无 OSPF peer 数据 → OSPF 未配置，需要生成草案
    2. 有 peer 但存在非 Full 邻居 → OSPF 不健康，需要生成草案
    3. 所有 peer 为 Full 且有 OSPF 路由 → OSPF 正常，不生成草案
    """
    ospf_analysis = analyze_ospf_config(diagnostics)

    # 全局判定：如果所有设备都有 Full 邻居且有 OSPF 路由，无需草案
    if ospf_analysis.all_peers_full and ospf_analysis.all_networks_advertised:
        return None

    # 逐设备判定是否需要配置
    needed_devices: list[dict] = []
    for cfg in _OSPF_CONFIGS:
        device_name = cfg["device"]
        device_analysis = None
        for da in ospf_analysis.device_analyses:
            if da.device_name == device_name:
                device_analysis = da
                break

        needs_ospf = False
        if device_analysis is None:
            # 无诊断数据，保守地认为需要配置
            needs_ospf = True
        elif not device_analysis.peers:
            # 无 OSPF 邻居 → OSPF 未配置
            needs_ospf = True
        elif any(p.state != "Full" for p in device_analysis.peers):
            # 有邻居但非 Full → OSPF 不健康，需要重新配置
            needs_ospf = True
        elif not device_analysis.ospf_routes:
            # 邻居 Full 但无 OSPF 路由 → 收敛中，不重复配置
            needs_ospf = False

        if needs_ospf:
            needed_devices.append(cfg)

    if not needed_devices:
        return None

    # 构建设备草案
    devices: list[DeviceConfigDraft] = []
    for cfg in needed_devices:
        device_name = cfg["device"]
        device_id = _find_device_id_by_name(adapter, device_name)
        if not device_id:
            continue

        networks = ", ".join(cfg["networks"])
        devices.append(DeviceConfigDraft(
            device_id=device_id,
            device_name=device_name,
            commands=cfg["commands"],
            purpose=f"配置 OSPF 进程 1，通告网段: {networks}",
            risk_level="medium",
            risk_warning="OSPF 配置将启用路由协议，影响路由表收敛",
        ))

    if not devices:
        return None

    # 稳定 draft_id：基于设备+命令内容哈希
    content_parts = []
    for d in devices:
        for cmd in d.commands:
            content_parts.append(f"{d.device_name}:{cmd}")
    content_hash = hashlib.sha256(
        "|".join(sorted(content_parts)).encode()
    ).hexdigest()[:12]
    draft_id = f"ospf-config-{content_hash}"

    # 检查缓存
    cached = _draft_cache.get(draft_id)
    if cached is not None:
        return cached

    warnings = [
        "本草案包含 OSPF 协议配置命令（ospf 1 / area 0 / network）",
        "OSPF 配置将启用动态路由协议，设备间将交换路由信息",
        "配置前将自动备份每台设备的当前配置",
        "配置执行后将自动验证 PC1/PC2 连通性",
    ]

    draft = ConfigDraft(
        draft_id=draft_id,
        created_at=datetime.now().isoformat(),
        purpose="配置 OSPF 路由协议（process 1, area 0），实现 PC1/PC2 互通",
        devices=devices,
        risk_summary="中风险：启用 OSPF 路由协议，将影响路由表收敛",
        warnings=warnings,
        requires_confirmation=True,
    )

    _draft_cache[draft_id] = draft
    return draft


def generate_vlan_draft(
    adapter: BaseAdapter,
    diagnostics: list,
) -> Optional[ConfigDraft]:
    """基于 VLAN 分析结果生成 VLAN 配置草案。

    判定逻辑：预期 VLAN 不存在于设备 → 需要配置。
    """
    vlan_analysis = analyze_vlan_config(diagnostics)

    # 全局判定：如果所有设备都已配置预期 VLAN，无需草案
    if vlan_analysis.all_vlans_configured:
        return None

    # 逐设备判定是否需要配置
    needed_devices: list[dict] = []
    for cfg in _VLAN_CONFIGS:
        device_name = cfg["device"]
        device_analysis = None
        for da in vlan_analysis.device_analyses:
            if da.device_name == device_name:
                device_analysis = da
                break

        needs_vlan = False
        if device_analysis is None:
            needs_vlan = True
        elif device_analysis.issues:
            # 有 issue 说明缺少 VLAN 或端口
            needs_vlan = True

        if needs_vlan:
            needed_devices.append(cfg)

    if not needed_devices:
        return None

    # 构建设备草案
    devices: list[DeviceConfigDraft] = []
    for cfg in needed_devices:
        device_name = cfg["device"]
        device_id = _find_device_id_by_name(adapter, device_name)
        if not device_id:
            continue

        devices.append(DeviceConfigDraft(
            device_id=device_id,
            device_name=device_name,
            commands=cfg["commands"],
            purpose=f"创建 VLAN 10 并分配端口",
            risk_level="medium",
            risk_warning="VLAN 配置将影响二层转发",
        ))

    if not devices:
        return None

    # 稳定 draft_id
    content_parts = []
    for d in devices:
        for cmd in d.commands:
            content_parts.append(f"{d.device_name}:{cmd}")
    content_hash = hashlib.sha256(
        "|".join(sorted(content_parts)).encode()
    ).hexdigest()[:12]
    draft_id = f"vlan-config-{content_hash}"

    # 检查缓存
    cached = _draft_cache.get(draft_id)
    if cached is not None:
        return cached

    warnings = [
        "本草案包含 VLAN 配置命令（vlan 10 / port GigabitEthernet0/0/0）",
        "VLAN 配置将影响二层转发域",
        "配置前将自动备份每台设备的当前配置",
    ]

    draft = ConfigDraft(
        draft_id=draft_id,
        created_at=datetime.now().isoformat(),
        purpose="创建 VLAN 10 并分配端口",
        devices=devices,
        risk_summary="中风险：VLAN 配置将影响二层转发域",
        warnings=warnings,
        requires_confirmation=True,
    )

    _draft_cache[draft_id] = draft
    return draft


def generate_dhcp_draft(
    adapter: BaseAdapter,
    diagnostics: list,
) -> Optional[ConfigDraft]:
    """基于 DHCP 分析结果生成 DHCP 配置草案。

    判定逻辑：任一交换机存在 VLAN/Vlanif/DHCP/端口缺口 → 需要配置。
    """
    from backend.services.dhcp_analysis import analyze_dhcp_config

    dhcp_analysis = analyze_dhcp_config(diagnostics)

    # 全局判定：如果所有配置项都已就绪，无需草案
    if (
        dhcp_analysis.all_vlans_configured
        and dhcp_analysis.all_vlanifs_configured
        and dhcp_analysis.dhcp_fully_configured
        and dhcp_analysis.all_ports_correct
    ):
        return None

    # 逐设备判定是否需要配置
    needed_devices: list[dict] = []
    for cfg in _DHCP_CONFIGS:
        device_name = cfg["device"]
        device_analysis = None
        for da in dhcp_analysis.device_analyses:
            if da.device_name == device_name:
                device_analysis = da
                break

        needs_dhcp = False
        if device_analysis is None:
            needs_dhcp = True
        elif device_analysis.issues:
            needs_dhcp = True

        if needs_dhcp:
            needed_devices.append(cfg)

    if not needed_devices:
        return None

    # 构建设备草案
    devices: list[DeviceConfigDraft] = []
    for cfg in needed_devices:
        device_name = cfg["device"]
        device_id = _find_device_id_by_name(adapter, device_name)
        if not device_id:
            continue

        devices.append(DeviceConfigDraft(
            device_id=device_id,
            device_name=device_name,
            commands=cfg["commands"],
            purpose=f"配置 DHCP 地址分发（VLAN/Vlanif/地址池/端口）",
            risk_level="medium",
            risk_warning="DHCP 配置将创建 VLAN、Vlanif 接口和地址池，影响二三层转发",
        ))

    if not devices:
        return None

    # 稳定 draft_id
    content_parts = []
    for d in devices:
        for cmd in d.commands:
            content_parts.append(f"{d.device_name}:{cmd}")
    content_hash = hashlib.sha256(
        "|".join(sorted(content_parts)).encode()
    ).hexdigest()[:12]
    draft_id = f"dhcp-config-{content_hash}"

    # 检查缓存
    cached = _draft_cache.get(draft_id)
    if cached is not None:
        return cached

    warnings = [
        "本草案包含 DHCP 地址分发配置（VLAN/Vlanif/DHCP enable/地址池/端口）",
        "LSW1 将作为 DHCP 服务器，LSW5/LSW2/LSW3/LSW4 配置 PC 接入口",
        "配置前将自动备份每台设备的当前配置",
        "配置执行后 PC1/PC2/PC3/PC4 应能自动获取 IP 地址",
    ]

    draft = ConfigDraft(
        draft_id=draft_id,
        created_at=datetime.now().isoformat(),
        purpose="配置 DHCP 地址分发：LSW1 创建 VLAN 10/20/30/40 + Vlanif + DHCP 池，接入/汇聚交换机配置端口",
        devices=devices,
        risk_summary="中风险：将创建 VLAN、Vlanif 接口、DHCP 地址池和端口配置",
        warnings=warnings,
        requires_confirmation=True,
    )

    _draft_cache[draft_id] = draft
    return draft


# --- 配置执行 ---

def apply_config_draft(
    draft: ConfigDraft,
    adapter: BaseAdapter,
    log_service: LogService,
    confirmed: bool,
) -> DeployResult:
    """执行配置草案。

    安全检查：
    1. 必须显式确认
    2. 所有命令必须通过白名单校验
    3. 每台设备执行前自动备份
    """
    now = datetime.now().isoformat()

    # 检查确认
    if not confirmed:
        log_service.log_config_deploy(
            draft.draft_id, success=False,
            detail="未确认，拒绝执行",
        )
        return DeployResult(
            draft_id=draft.draft_id,
            success=False,
            device_results=[],
            verification=None,
            deployed_at=now,
            error="未确认：配置下发需要显式传入 confirmed=true",
        )

    # 白名单校验
    for device_draft in draft.devices:
        for cmd in device_draft.commands:
            if not _validate_command(cmd):
                log_service.log_config_deploy(
                    draft.draft_id, success=False,
                    detail=f"命令白名单校验失败: {cmd}",
                )
                return DeployResult(
                    draft_id=draft.draft_id,
                    success=False,
                    device_results=[],
                    verification=None,
                    deployed_at=now,
                    error=f"命令白名单校验失败: {cmd}",
                )

    # 逐设备执行
    device_results: list[DeviceDeployResult] = []
    all_success = True

    for device_draft in draft.devices:
        # 备份
        backup_success = True
        backup_error = None
        backup_path = None
        try:
            backup = adapter.backup_config(device_draft.device_id)
            backup_path = backup.backup_path
            log_service.log_config_backup(
                device_id=device_draft.device_id,
                device_name=device_draft.device_name,
                success=True,
                detail=f"配置备份成功: {backup.backup_path}",
            )
        except (DeviceNotFoundError, DeviceConnectionError) as e:
            backup_success = False
            backup_error = str(e)
            log_service.log_config_backup(
                device_id=device_draft.device_id,
                device_name=device_draft.device_name,
                success=False,
                detail=f"配置备份失败: {e}",
            )
            device_results.append(DeviceDeployResult(
                device_id=device_draft.device_id,
                device_name=device_draft.device_name,
                backup_success=False,
                backup_error=backup_error,
                command_results=[],
                all_commands_success=False,
                error=f"备份失败，中止执行: {e}",
            ))
            all_success = False
            continue

        # 执行配置命令
        try:
            cmd_results = adapter.run_config_commands(
                device_draft.device_id,
                device_draft.commands,
            )
            cmd_all_ok = all(r.success for r in cmd_results)

            for r in cmd_results:
                log_service.log_config_deploy(
                    draft.draft_id,
                    success=r.success,
                    detail=f"[{device_draft.device_name}] {r.command}: {'成功' if r.success else r.error}",
                )

            device_results.append(DeviceDeployResult(
                device_id=device_draft.device_id,
                device_name=device_draft.device_name,
                backup_success=True,
                backup_error=None,
                backup_path=backup_path,
                command_results=cmd_results,
                all_commands_success=cmd_all_ok,
            ))
            if not cmd_all_ok:
                all_success = False

        except (DeviceNotFoundError, DeviceConnectionError) as e:
            log_service.log_config_deploy(
                draft.draft_id,
                success=False,
                detail=f"[{device_draft.device_name}] 配置执行异常: {e}",
            )
            device_results.append(DeviceDeployResult(
                device_id=device_draft.device_id,
                device_name=device_draft.device_name,
                backup_success=True,
                backup_error=None,
                backup_path=backup_path,
                command_results=[],
                all_commands_success=False,
                error=str(e),
            ))
            all_success = False

    log_service.log_config_deploy(
        draft.draft_id,
        success=all_success,
        detail=f"配置{'成功' if all_success else '部分失败'}，设备 {len(device_results)} 台",
    )

    return DeployResult(
        draft_id=draft.draft_id,
        success=all_success,
        device_results=device_results,
        verification=None,  # 由调用方补充验证
        deployed_at=now,
    )


def verify_after_deploy(
    adapter: BaseAdapter,
) -> VerificationResult:
    """执行后验证：获取最新诊断数据，检查连通性。"""
    from backend.adapters.base_adapter import DeviceDiagnostics, CommandOutput
    from backend.services.connectivity_analysis import analyze_pc_connectivity

    # 获取所有路由器的最新诊断数据
    diags: list[DeviceDiagnostics] = []
    for device in adapter.list_devices():
        if device.type == "pc":
            continue
        try:
            diag = adapter.get_device_diagnostics(device.id)
            diags.append(diag)
        except (DeviceNotFoundError, DeviceConnectionError):
            # 诊断失败时构造空结果
            diags.append(DeviceDiagnostics(
                device_id=device.id,
                device_name=device.name,
                collected_at=datetime.now().isoformat(),
                commands=[CommandOutput(
                    command="<connection>",
                    success=False,
                    error="连接失败",
                )],
            ))

    analysis = analyze_pc_connectivity(diags)

    return VerificationResult(
        pc1_to_pc2_reachable=analysis.pc1_to_pc2_reachable or False,
        pc2_to_pc1_reachable=analysis.pc2_to_pc1_reachable or False,
        gaps=analysis.gaps,
        verified_at=datetime.now().isoformat(),
    )



# --- 最终状态判定（共用逻辑）---

@dataclass
class FinalSuccessCheck:
    """final-report 视角的成功判定结果。"""
    is_success: bool
    health_ready: bool
    both_reachable: bool
    deploy_ok: bool
    reason: Optional[str] = None


def check_final_success(
    adapter: BaseAdapter,
) -> FinalSuccessCheck:
    """判定当前是否满足 final-report 视角的 success 条件。

    条件（全部满足）：
    1. health.ready = true
    2. PC1→PC2 和 PC2→PC1 均 reachable
    3. 如果存在 latest_deploy 记录，则 latest_deploy.success = true

    供 save preview / save apply / final-report 共用，避免重复逻辑。
    """
    from backend.services.device_service import check_ensp_health

    # 1. 环境健康
    health = check_ensp_health()
    if not health.ready:
        return FinalSuccessCheck(
            is_success=False, health_ready=False,
            both_reachable=False, deploy_ok=True,
            reason="环境健康检查未通过",
        )

    # 2. 连通性
    from backend.adapters.base_adapter import DeviceDiagnostics, CommandOutput
    diags: list[DeviceDiagnostics] = []
    for device in adapter.list_devices():
        if device.type == "pc":
            continue
        try:
            diag = adapter.get_device_diagnostics(device.id)
            diags.append(diag)
        except (DeviceNotFoundError, DeviceConnectionError):
            diags.append(DeviceDiagnostics(
                device_id=device.id, device_name=device.name,
                collected_at=datetime.now().isoformat(),
                commands=[CommandOutput(command="<connection>", success=False, error="连接失败")],
            ))

    connectivity = analyze_pc_connectivity(diags)
    pc1_ok = connectivity.pc1_to_pc2_reachable or False
    pc2_ok = connectivity.pc2_to_pc1_reachable or False
    both_ok = pc1_ok and pc2_ok

    if not both_ok:
        return FinalSuccessCheck(
            is_success=False, health_ready=True,
            both_reachable=False, deploy_ok=True,
            reason=f"连通性未满足：{'; '.join(connectivity.gaps)}",
        )

    # 3. 部署记录
    latest_deploy = get_latest_deploy()
    if latest_deploy is not None and not latest_deploy.success:
        return FinalSuccessCheck(
            is_success=False, health_ready=True,
            both_reachable=True, deploy_ok=False,
            reason="最近一次配置执行失败",
        )

    return FinalSuccessCheck(
        is_success=True, health_ready=True,
        both_reachable=True, deploy_ok=True,
    )


# --- 配置保存 ---

def save_all_configs(
    adapter: BaseAdapter,
    log_service: LogService,
) -> SaveAllResult:
    """对所有受管网络设备执行 save 命令。

    前置条件（ENABLE_REAL_ENSP、confirmed、final_success）由调用方检查。
    本函数仅执行实际 save 操作，仅处理路由器和交换机。
    """
    now = datetime.now().isoformat()

    device_results: list[DeviceSaveResult] = []
    all_success = True

    for device in adapter.list_devices():
        if device.type not in {"router", "switch"}:
            continue

        try:
            result = adapter.save_config(device.id)
            log_service.log_config_save(
                device_id=device.id,
                device_name=device.name,
                success=result.success,
                detail=f"save {'成功' if result.success else result.error}",
            )
            device_results.append(DeviceSaveResult(
                device_id=device.id,
                device_name=device.name,
                success=result.success,
                output=result.output,
                error=result.error,
            ))
            if not result.success:
                all_success = False
        except (DeviceNotFoundError, DeviceConnectionError) as e:
            log_service.log_config_save(
                device_id=device.id,
                device_name=device.name,
                success=False,
                detail=f"save 失败: {e}",
            )
            device_results.append(DeviceSaveResult(
                device_id=device.id,
                device_name=device.name,
                success=False,
                error=str(e),
            ))
            all_success = False

    return SaveAllResult(
        success=all_success,
        device_results=device_results,
        saved_at=now,
    )
