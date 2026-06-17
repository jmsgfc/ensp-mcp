"""PC1/PC2 连通性分析模块。

基于 AR1/AR2/AR3 的诊断数据，分析 PC1 与 PC2 为什么不能互通，
输出结构化分析结果和最小配置建议草案。

不做真实配置下发，仅输出分析和建议。
"""

import re
from dataclasses import dataclass, field
from typing import Optional

from backend.adapters.base_adapter import DeviceDiagnostics


# --- 数据模型 ---

@dataclass
class InterfaceStatus:
    """接口状态摘要。"""
    name: str
    phy_up: bool
    protocol_up: bool
    ip_address: Optional[str] = None
    status: Optional[str] = None


@dataclass
class RouteEntry:
    """路由表条目。"""
    destination: str
    mask: str
    proto: str
    next_hop: Optional[str] = None
    interface: Optional[str] = None


@dataclass
class DeviceAnalysis:
    """单台设备的分析结果。"""
    device_name: str
    interfaces: list[InterfaceStatus] = field(default_factory=list)
    routes: list[RouteEntry] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)


@dataclass
class ConnectivityAnalysis:
    """PC1/PC2 连通性分析结果。"""
    pc1_network: str
    pc2_network: str
    path: list[str]
    device_analyses: list[DeviceAnalysis] = field(default_factory=list)
    pc1_to_pc2_reachable: Optional[bool] = None
    pc2_to_pc1_reachable: Optional[bool] = None
    gaps: list[str] = field(default_factory=list)
    config_suggestions: list[str] = field(default_factory=list)


@dataclass
class OspfPeer:
    """OSPF 邻居条目。"""
    router_id: str
    address: str
    state: str
    interface: Optional[str] = None


@dataclass
class OspfDeviceAnalysis:
    """单台设备的 OSPF 分析结果。"""
    device_name: str
    ospf_process_id: Optional[int] = None
    router_id: Optional[str] = None
    area: Optional[str] = None
    peers: list[OspfPeer] = field(default_factory=list)
    ospf_routes: list[RouteEntry] = field(default_factory=list)
    interfaces_advertised: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)


@dataclass
class OspfAnalysis:
    """OSPF 配置分析结果。"""
    device_analyses: list[OspfDeviceAnalysis] = field(default_factory=list)
    all_peers_full: Optional[bool] = None
    all_networks_advertised: Optional[bool] = None
    gaps: list[str] = field(default_factory=list)
    config_suggestions: list[str] = field(default_factory=list)


# --- 解析函数 ---

def parse_interface_brief(output: str) -> list[InterfaceStatus]:
    """解析 display interface brief 输出。"""
    interfaces = []
    for line in output.splitlines():
        line = line.strip()
        if not line or line.startswith("Interface") or line.startswith("---"):
            continue
        parts = line.split()
        if len(parts) >= 3:
            name = parts[0]
            phy = parts[1].lower()
            protocol = parts[2].lower()
            interfaces.append(InterfaceStatus(
                name=name,
                phy_up=phy == "up",
                protocol_up=protocol in ("up", "up(s)"),
            ))
    return interfaces


def parse_ip_interface_brief(output: str) -> dict[str, InterfaceStatus]:
    """解析 display ip interface brief 输出，返回接口名 -> InterfaceStatus 映射。"""
    result = {}
    for line in output.splitlines():
        line = line.strip()
        if not line or line.startswith("Interface") or line.startswith("---"):
            continue
        parts = line.split()
        if len(parts) >= 4:
            name = parts[0]
            ip_addr = parts[1]
            status = parts[3] if len(parts) > 3 else None
            result[name] = InterfaceStatus(
                name=name,
                phy_up=True,  # 从 ip interface brief 无法判断 phy，后续合并
                protocol_up=True,
                ip_address=ip_addr if ip_addr != "unassigned" else None,
                status=status,
            )
    return result


def parse_routing_table(output: str) -> list[RouteEntry]:
    """解析 display ip routing-table 输出。"""
    routes = []
    for line in output.splitlines():
        line = line.strip()
        if not line or line.startswith("Route") or line.startswith("---"):
            continue
        if line.startswith("Routing Tables") or line.startswith("Destinations"):
            continue
        if line.startswith("Destination"):
            continue  # 表头行
        # 格式: Destination/Mask  Proto  Pre  Cost  Flags  NextHop  Interface
        parts = line.split()
        if len(parts) >= 2 and "/" in parts[0]:
            dest_mask = parts[0].split("/", 1)
            dest = dest_mask[0]
            mask = dest_mask[1] if len(dest_mask) > 1 else ""
            proto = parts[1] if len(parts) > 1 else ""
            next_hop = parts[5] if len(parts) > 5 else None
            iface = parts[6] if len(parts) > 6 else None
            routes.append(RouteEntry(
                destination=dest,
                mask=mask,
                proto=proto,
                next_hop=next_hop,
                interface=iface,
            ))
    return routes


def merge_interfaces(
    brief: list[InterfaceStatus],
    ip_brief: dict[str, InterfaceStatus],
) -> list[InterfaceStatus]:
    """合并 display interface brief 和 display ip interface brief 的结果。"""
    merged = []
    for iface in brief:
        ip_info = ip_brief.get(iface.name)
        merged.append(InterfaceStatus(
            name=iface.name,
            phy_up=iface.phy_up,
            protocol_up=iface.protocol_up,
            ip_address=ip_info.ip_address if ip_info else None,
            status=ip_info.status if ip_info else None,
        ))
    return merged


# --- 分析逻辑 ---

def _get_command_output(diag: DeviceDiagnostics, command: str) -> Optional[str]:
    """从诊断数据中获取指定命令的输出。"""
    for cmd in diag.commands:
        if cmd.command == command and cmd.success:
            return cmd.output
    return None


def _analyze_device(diag: DeviceDiagnostics) -> DeviceAnalysis:
    """分析单台设备的诊断数据。"""
    analysis = DeviceAnalysis(device_name=diag.device_name)

    # 解析接口状态
    brief_output = _get_command_output(diag, "display interface brief")
    ip_brief_output = _get_command_output(diag, "display ip interface brief")

    if brief_output and ip_brief_output:
        brief = parse_interface_brief(brief_output)
        ip_brief = parse_ip_interface_brief(ip_brief_output)
        analysis.interfaces = merge_interfaces(brief, ip_brief)
    elif brief_output:
        analysis.interfaces = parse_interface_brief(brief_output)

    # 解析路由表
    route_output = _get_command_output(diag, "display ip routing-table")
    if route_output:
        analysis.routes = parse_routing_table(route_output)

    # 检查接口问题
    for iface in analysis.interfaces:
        if iface.name == "NULL0":
            continue
        if not iface.phy_up:
            analysis.issues.append(f"接口 {iface.name} 物理层 down")
        if not iface.protocol_up:
            analysis.issues.append(f"接口 {iface.name} 协议层 down")
        if iface.ip_address is None and iface.phy_up:
            analysis.issues.append(f"接口 {iface.name} 未配置 IP 地址")

    return analysis


def _has_route_to(routes: list[RouteEntry], network: str) -> bool:
    """检查路由表中是否有到指定网段的路由。"""
    for route in routes:
        if route.destination == network:
            return True
    return False


def analyze_pc_connectivity(
    diagnostics: list[DeviceDiagnostics],
) -> ConnectivityAnalysis:
    """分析 PC1/PC2 连通性。

    拓扑路径：PC1(192.168.2.0/24) → AR2 → AR1 → AR3 → PC2(192.168.3.0/24)

    Args:
        diagnostics: AR1/AR2/AR3 的诊断数据列表

    Returns:
        结构化的连通性分析结果
    """
    PC1_NETWORK = "192.168.2.0"
    PC2_NETWORK = "192.168.3.0"
    PATH = ["PC1", "AR2", "AR1", "AR3", "PC2"]

    result = ConnectivityAnalysis(
        pc1_network=PC1_NETWORK,
        pc2_network=PC2_NETWORK,
        path=PATH,
    )

    # 按设备名索引诊断数据
    diag_by_name: dict[str, DeviceDiagnostics] = {}
    for diag in diagnostics:
        diag_by_name[diag.device_name] = diag

    # 分析每台设备
    analyses: dict[str, DeviceAnalysis] = {}
    for name in ["AR1", "AR2", "AR3"]:
        diag = diag_by_name.get(name)
        if diag:
            analyses[name] = _analyze_device(diag)
            result.device_analyses.append(analyses[name])
        else:
            result.gaps.append(f"缺少 {name} 的诊断数据")

    # --- 检查 PC1 → PC2 方向 ---
    pc1_to_pc2_ok = True

    # 检查 AR2：PC1 的网关
    ar2 = analyses.get("AR2")
    if ar2:
        # AR2 GE0/0/0 应该是 up 且有 192.168.2.1
        ge0_0_0 = next((i for i in ar2.interfaces if i.name == "GE0/0/0"), None)
        if ge0_0_0 and not ge0_0_0.phy_up:
            result.gaps.append("AR2 GE0/0/0 接口 down，PC1 无法接入")
            pc1_to_pc2_ok = False

        # AR2 需要有到 192.168.3.0/24 的路由
        if not _has_route_to(ar2.routes, PC2_NETWORK):
            result.gaps.append("AR2 缺少到 192.168.3.0/24 (PC2 网段) 的路由")
            pc1_to_pc2_ok = False

    # 检查 AR1：中间路由器
    ar1 = analyses.get("AR1")
    if ar1:
        # AR1 需要有到 192.168.2.0/24 和 192.168.3.0/24 的路由
        if not _has_route_to(ar1.routes, PC1_NETWORK):
            result.gaps.append("AR1 缺少到 192.168.2.0/24 (PC1 网段) 的路由")
            pc1_to_pc2_ok = False
        if not _has_route_to(ar1.routes, PC2_NETWORK):
            result.gaps.append("AR1 缺少到 192.168.3.0/24 (PC2 网段) 的路由")
            pc1_to_pc2_ok = False

    # 检查 AR3：PC2 的网关
    ar3 = analyses.get("AR3")
    if ar3:
        # AR3 GE0/0/0 应该是 up 且有 192.168.3.1
        ge0_0_0 = next((i for i in ar3.interfaces if i.name == "GE0/0/0"), None)
        if ge0_0_0 and not ge0_0_0.phy_up:
            result.gaps.append("AR3 GE0/0/0 接口 down，PC2 无法接入")
            pc1_to_pc2_ok = False

        # AR3 需要有到 192.168.2.0/24 的路由（回程路由）
        if not _has_route_to(ar3.routes, PC1_NETWORK):
            result.gaps.append("AR3 缺少到 192.168.2.0/24 (PC1 网段) 的路由")
            pc1_to_pc2_ok = False

    result.pc1_to_pc2_reachable = pc1_to_pc2_ok

    # --- 检查 PC2 → PC1 方向（对称检查）---
    pc2_to_pc1_ok = True

    if ar3:
        ge0_0_0 = next((i for i in ar3.interfaces if i.name == "GE0/0/0"), None)
        if ge0_0_0 and not ge0_0_0.phy_up:
            pc2_to_pc1_ok = False
        if not _has_route_to(ar3.routes, PC1_NETWORK):
            pc2_to_pc1_ok = False

    if ar1:
        if not _has_route_to(ar1.routes, PC1_NETWORK):
            pc2_to_pc1_ok = False
        if not _has_route_to(ar1.routes, PC2_NETWORK):
            pc2_to_pc1_ok = False

    if ar2:
        ge0_0_0 = next((i for i in ar2.interfaces if i.name == "GE0/0/0"), None)
        if ge0_0_0 and not ge0_0_0.phy_up:
            pc2_to_pc1_ok = False
        if not _has_route_to(ar2.routes, PC2_NETWORK):
            pc2_to_pc1_ok = False

    result.pc2_to_pc1_reachable = pc2_to_pc1_ok

    # --- 生成配置建议草案 ---
    if result.gaps:
        result.config_suggestions = _generate_config_suggestions(analyses, result.gaps)

    return result


def _generate_config_suggestions(
    analyses: dict[str, DeviceAnalysis],
    gaps: list[str],
) -> list[str]:
    """根据分析缺口生成最小配置建议草案。"""
    suggestions = []
    warning = "[仅建议，不执行]"

    for gap in gaps:
        if "AR2 缺少到 192.168.3.0/24" in gap:
            suggestions.append(
                f"{warning} [AR2] 建议添加静态路由:\n"
                "  system-view\n"
                "  ip route-static 192.168.3.0 255.255.255.0 10.0.12.1\n"
                "  （下一跳指向 AR1 的 GE0/0/1 接口地址 10.0.12.1）"
            )
        elif "AR3 缺少到 192.168.2.0/24" in gap:
            suggestions.append(
                f"{warning} [AR3] 建议添加静态路由:\n"
                "  system-view\n"
                "  ip route-static 192.168.2.0 255.255.255.0 10.0.13.1\n"
                "  （下一跳指向 AR1 的 GE0/0/2 接口地址 10.0.13.1）"
            )
        elif "AR1 缺少到 192.168.2.0/24" in gap:
            suggestions.append(
                f"{warning} [AR1] 建议添加静态路由:\n"
                "  system-view\n"
                "  ip route-static 192.168.2.0 255.255.255.0 10.0.12.2\n"
                "  （下一跳指向 AR2 的 GE0/0/1 接口地址 10.0.12.2）"
            )
        elif "AR1 缺少到 192.168.3.0/24" in gap:
            suggestions.append(
                f"{warning} [AR1] 建议添加静态路由:\n"
                "  system-view\n"
                "  ip route-static 192.168.3.0 255.255.255.0 10.0.13.2\n"
                "  （下一跳指向 AR3 的 GE0/0/1 接口地址 10.0.13.2）"
            )
        elif "接口 down" in gap:
            suggestions.append(
                f"{warning} [设备] 建议检查物理连接: {gap}"
            )
        elif "未配置 IP 地址" in gap:
            suggestions.append(
                f"{warning} [设备] 建议配置 IP 地址: {gap}"
            )

    return suggestions


# --- OSPF 分析 ---

# 每台设备预期在 OSPF area 0 中通告的网段（当前拓扑专用）
_EXPECTED_OSPF_NETWORKS: dict[str, list[str]] = {
    "AR1": ["192.168.1.0", "10.0.12.0", "10.0.13.0"],
    "AR2": ["192.168.2.0", "10.0.12.0"],
    "AR3": ["192.168.3.0", "10.0.13.0"],
}


def parse_ospf_peer(output: str) -> list[OspfPeer]:
    """解析 display ospf peer 输出。"""
    peers = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        # 跳过标题行
        if line.startswith("OSPF") or line.startswith("Neighbor"):
            continue
        if line.startswith("Area") or line.startswith("Router ID"):
            continue
        parts = line.split()
        # 格式: RouterID  Address  Pri  Dead-Time  State  Interface
        if len(parts) >= 5 and "." in parts[0]:
            peers.append(OspfPeer(
                router_id=parts[0],
                address=parts[1],
                state=parts[4],
                interface=parts[5] if len(parts) > 5 else None,
            ))
    return peers


def analyze_ospf_config(
    diagnostics: list[DeviceDiagnostics],
) -> OspfAnalysis:
    """分析 OSPF 配置状态。

    检查每台路由器是否：
    1. 有 OSPF 进程且 peer 状态为 Full
    2. 路由表中有通过 OSPF 学到的远端网段路由

    Args:
        diagnostics: AR1/AR2/AR3 的诊断数据列表

    Returns:
        结构化的 OSPF 分析结果
    """
    result = OspfAnalysis()

    diag_by_name: dict[str, DeviceDiagnostics] = {}
    for diag in diagnostics:
        diag_by_name[diag.device_name] = diag

    all_peers_ok = True
    all_networks_ok = True

    for device_name in ["AR1", "AR2", "AR3"]:
        diag = diag_by_name.get(device_name)
        if not diag:
            result.gaps.append(f"缺少 {device_name} 的诊断数据")
            all_peers_ok = False
            all_networks_ok = False
            continue

        analysis = OspfDeviceAnalysis(device_name=device_name)

        # 1. 解析 OSPF 邻居
        peer_output = _get_command_output(diag, "display ospf peer")
        if peer_output:
            analysis.peers = parse_ospf_peer(peer_output)
            for peer in analysis.peers:
                if peer.state != "Full":
                    analysis.issues.append(
                        f"OSPF 邻居 {peer.router_id} 状态为 {peer.state}，预期 Full"
                    )
                    all_peers_ok = False
        else:
            analysis.issues.append("缺少 display ospf peer 输出，OSPF 可能未配置")
            all_peers_ok = False

        # 2. 检查路由表中的 OSPF 路由
        route_output = _get_command_output(diag, "display ip routing-table")
        if route_output:
            routes = parse_routing_table(route_output)
            analysis.ospf_routes = [r for r in routes if r.proto == "OSPF"]
            expected = _EXPECTED_OSPF_NETWORKS.get(device_name, [])
            for network in expected:
                has_route = any(
                    r.destination == network
                    for r in routes
                    if r.proto in ("OSPF", "Direct")
                )
                if not has_route:
                    analysis.issues.append(
                        f"路由表中缺少 {network} 的 OSPF 或 Direct 路由"
                    )
                    all_networks_ok = False

        # 3. 从 brief 输出提取 Router ID
        brief_output = _get_command_output(diag, "display ospf brief")
        if brief_output:
            for line in brief_output.splitlines():
                if "RouterID:" in line:
                    parts = line.split("RouterID:")
                    if len(parts) > 1:
                        analysis.router_id = parts[1].strip().split()[0]

        result.device_analyses.append(analysis)

    result.all_peers_full = all_peers_ok
    result.all_networks_advertised = all_networks_ok

    # 汇总 gaps
    for da in result.device_analyses:
        for issue in da.issues:
            result.gaps.append(f"[{da.device_name}] {issue}")

    # 生成配置建议
    if result.gaps:
        result.config_suggestions = _generate_ospf_config_suggestions(
            result.device_analyses, result.gaps
        )

    return result


def _generate_ospf_config_suggestions(
    analyses: list[OspfDeviceAnalysis],
    gaps: list[str],
) -> list[str]:
    """根据 OSPF 分析缺口生成配置建议。"""
    suggestions = []
    warning = "[仅建议，不执行]"

    for gap in gaps:
        if "OSPF 可能未配置" in gap:
            device = gap.split("]")[0].strip("[")
            if device in _EXPECTED_OSPF_NETWORKS:
                networks = _EXPECTED_OSPF_NETWORKS[device]
                network_cmds = "\n".join(
                    f"    network {n} 0.0.0.255" for n in networks
                )
                suggestions.append(
                    f"{warning} [{device}] 建议配置 OSPF:\n"
                    f"  system-view\n"
                    f"  ospf 1\n"
                    f"  area 0\n"
                    f"{network_cmds}"
                )
        elif "邻居" in gap and "Full" not in gap:
            suggestions.append(
                f"{warning} OSPF 邻居未达到 Full 状态，检查链路和 OSPF 参数: {gap}"
            )

    return suggestions


# --- VLAN 分析 ---

@dataclass
class VlanEntry:
    """VLAN 条目。"""
    vlan_id: int
    vlan_type: str  # "common" / "super" / "sub"
    ports: list[str] = field(default_factory=list)


@dataclass
class VlanDeviceAnalysis:
    """单台设备的 VLAN 分析结果。"""
    device_name: str
    vlans: list[VlanEntry] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)


@dataclass
class VlanAnalysis:
    """VLAN 配置分析结果。"""
    device_analyses: list[VlanDeviceAnalysis] = field(default_factory=list)
    all_vlans_configured: Optional[bool] = None
    all_ports_assigned: Optional[bool] = None
    gaps: list[str] = field(default_factory=list)
    config_suggestions: list[str] = field(default_factory=list)


_EXPECTED_VLANS: dict[str, list[int]] = {
    "AR1": [10],
    "AR2": [10],
    "AR3": [10],
}


def parse_vlan(output: str) -> list[VlanEntry]:
    """解析 display vlan 输出。"""
    vlans: list[VlanEntry] = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        # 跳过表头和分隔线
        if line.startswith("---") or line.startswith("U:") or line.startswith("The total"):
            continue
        if line.startswith("VID"):
            continue
        # 匹配 VLAN 行: VID  Type  Ports
        parts = line.split()
        if len(parts) >= 2 and parts[0].isdigit():
            vlan_id = int(parts[0])
            vlan_type = parts[1] if len(parts) > 1 else "common"
            # 端口从第 3 列开始
            ports = []
            if len(parts) > 2:
                ports = parts[2:]
            vlans.append(VlanEntry(
                vlan_id=vlan_id,
                vlan_type=vlan_type,
                ports=ports,
            ))
    return vlans


def analyze_vlan_config(
    diagnostics: list[DeviceDiagnostics],
) -> VlanAnalysis:
    """分析 VLAN 配置状态。"""
    result = VlanAnalysis()
    diag_map = {d.device_name: d for d in diagnostics}
    all_configured = True
    all_ports_ok = True

    for device_name, expected_ids in _EXPECTED_VLANS.items():
        diag = diag_map.get(device_name)
        analysis = VlanDeviceAnalysis(device_name=device_name)

        if not diag:
            analysis.issues.append("无诊断数据")
            all_configured = False
            result.device_analyses.append(analysis)
            continue

        vlan_output = _get_command_output(diag, "display vlan")
        vlans = parse_vlan(vlan_output) if vlan_output else []
        analysis.vlans = vlans

        vlan_id_set = {v.vlan_id for v in vlans}

        for vid in expected_ids:
            if vid not in vlan_id_set:
                analysis.issues.append(f"缺少 VLAN {vid}")
                all_configured = False
            else:
                # VLAN 存在，检查端口
                vlan_entry = next(v for v in vlans if v.vlan_id == vid)
                if not vlan_entry.ports:
                    analysis.issues.append(f"VLAN {vid} 无端口成员")
                    all_ports_ok = False

        result.device_analyses.append(analysis)

    result.all_vlans_configured = all_configured
    result.all_ports_assigned = all_ports_ok

    # 汇总 gaps
    for da in result.device_analyses:
        for issue in da.issues:
            result.gaps.append(f"[{da.device_name}] {issue}")

    # 生成配置建议
    if result.gaps:
        result.config_suggestions = _generate_vlan_config_suggestions(
            result.device_analyses, result.gaps
        )

    return result


def _generate_vlan_config_suggestions(
    analyses: list[VlanDeviceAnalysis],
    gaps: list[str],
) -> list[str]:
    """根据 VLAN 分析缺口生成配置建议。"""
    suggestions = []
    warning = "[仅建议，不执行]"

    for gap in gaps:
        if "缺少 VLAN" in gap:
            device = gap.split("]")[0].strip("[")
            if device in _EXPECTED_VLANS:
                vlan_ids = _EXPECTED_VLANS[device]
                vlan_cmds = "\n".join(f"  vlan {vid}" for vid in vlan_ids)
                suggestions.append(
                    f"{warning} [{device}] 建议创建 VLAN:\n"
                    f"  system-view\n"
                    f"{vlan_cmds}"
                )
        elif "无端口成员" in gap:
            suggestions.append(
                f"{warning} VLAN 存在但无端口成员，需检查端口分配: {gap}"
            )

    return suggestions
