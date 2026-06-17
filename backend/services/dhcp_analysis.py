"""DHCP 地址分发分析模块。

基于 LSW1/LSW2/LSW3/LSW4 的诊断数据，分析 DHCP 地址分发配置状态，
输出结构化分析结果和最小配置建议草案。

不做真实配置下发，仅输出分析和建议。
"""

import re
from dataclasses import dataclass, field
from typing import Optional

from backend.adapters.base_adapter import DeviceDiagnostics
from backend.services.connectivity_analysis import _get_command_output, parse_vlan


# --- 数据模型 ---

@dataclass
class DhcpPoolInfo:
    """DHCP 地址池信息。"""
    name: str
    network: str
    gateway: str
    mask: Optional[str] = None
    lease: Optional[str] = None


@dataclass
class VlanifInfo:
    """Vlanif 接口信息。"""
    vlan_id: int
    ip_address: Optional[str] = None
    subnet_mask: Optional[str] = None
    dhcp_select: Optional[str] = None  # "global" / "interface" / None


@dataclass
class DhcpSwitchAnalysis:
    """单台交换机的 DHCP 分析结果。"""
    device_name: str
    device_type: str  # "l3_switch" / "l2_switch"
    vlans: list[int] = field(default_factory=list)
    vlanifs: list[VlanifInfo] = field(default_factory=list)
    dhcp_enabled: Optional[bool] = None
    dhcp_pools: list[DhcpPoolInfo] = field(default_factory=list)
    access_ports: dict[str, int] = field(default_factory=dict)  # port -> vlan_id
    trunk_ports: dict[str, list[int]] = field(default_factory=dict)  # port -> allowed vlans
    issues: list[str] = field(default_factory=list)


@dataclass
class DhcpAnalysis:
    """DHCP 地址分发分析结果。"""
    device_analyses: list[DhcpSwitchAnalysis] = field(default_factory=list)
    all_vlans_configured: Optional[bool] = None
    all_vlanifs_configured: Optional[bool] = None
    dhcp_fully_configured: Optional[bool] = None
    all_ports_correct: Optional[bool] = None
    gaps: list[str] = field(default_factory=list)
    config_suggestions: list[str] = field(default_factory=list)


# --- 预期配置（当前拓扑专用） ---

_EXPECTED_DHCP_VLANS: dict[str, list[int]] = {
    "LSW1": [10, 20, 30, 40],
    "LSW6": [10, 20, 30, 40],
    "LSW7": [10, 20, 30, 40],
    "LSW5": [10],
    "LSW2": [20],
    "LSW3": [30],
    "LSW4": [40],
}

_EXPECTED_VLANIFS: dict[str, dict[int, str]] = {
    "LSW1": {
        10: "192.168.10.1",
        20: "192.168.20.1",
        30: "192.168.30.1",
        40: "192.168.40.1",
    },
}

_EXPECTED_POOLS: dict[str, dict[str, str]] = {
    "LSW1": {
        "vlan10": "192.168.10.0",
        "vlan20": "192.168.20.0",
        "vlan30": "192.168.30.0",
        "vlan40": "192.168.40.0",
    },
}

_EXPECTED_ACCESS_PORTS: dict[str, dict[str, int]] = {
    "LSW5": {"Ethernet0/0/2": 10},
    "LSW2": {"Ethernet0/0/2": 20},
    "LSW3": {"Ethernet0/0/2": 30},
    "LSW4": {"Ethernet0/0/2": 40},
}

_EXPECTED_TRUNK_PORTS: dict[str, dict[str, list[int]]] = {
    "LSW1": {"GE0/0/1": [10, 20, 30, 40], "GE0/0/2": [10, 20, 30, 40]},
    "LSW6": {
        "Ethernet0/0/1": [10, 20, 30, 40],
        "Ethernet0/0/2": [10, 20, 30, 40],
        "Ethernet0/0/3": [10, 20, 30, 40],
    },
    "LSW7": {
        "Ethernet0/0/1": [10, 20, 30, 40],
        "Ethernet0/0/2": [10, 20, 30, 40],
        "Ethernet0/0/3": [10, 20, 30, 40],
    },
    "LSW5": {"Ethernet0/0/1": [10, 20, 30, 40]},
    "LSW2": {"Ethernet0/0/1": [10, 20, 30, 40]},
    "LSW3": {"Ethernet0/0/1": [10, 20, 30, 40]},
    "LSW4": {"Ethernet0/0/3": [10, 20, 30, 40]},
}

# L3 交换机（有 Vlanif/DHCP pool）
_L3_SWITCHES = {"LSW1"}


def build_dhcp_config_probe_commands(device_name: str) -> list[str]:
    """Return the targeted config queries needed for DHCP analysis."""
    commands: list[str] = []

    if device_name in _L3_SWITCHES:
        for vlan_id in sorted(_EXPECTED_VLANIFS.get(device_name, {})):
            commands.append(
                f"display current-configuration interface Vlanif{vlan_id}"
            )

    for port_name in sorted(_EXPECTED_TRUNK_PORTS.get(device_name, {})):
        full_name = (
            "GigabitEthernet" + port_name[len("GE"):]
            if port_name.startswith("GE")
            else port_name
        )
        commands.append(
            f"display current-configuration interface {full_name}"
        )

    for port_name in sorted(_EXPECTED_ACCESS_PORTS.get(device_name, {})):
        commands.append(
            f"display current-configuration interface {port_name}"
        )

    return commands


# --- 解析函数 ---

def parse_ip_pool(output: str) -> list[DhcpPoolInfo]:
    """解析 display ip pool 输出。"""
    pools: list[DhcpPoolInfo] = []
    current: dict[str, str] = {}

    for line in output.splitlines():
        line = line.strip()
        if not line or line.startswith("---"):
            continue

        # 检测新 pool 块开始
        if "Pool-name" in line:
            if current:
                pools.append(_build_pool(current))
                current = {}
            parts = line.split(":", 1)
            if len(parts) > 1:
                current["name"] = parts[1].strip()
            continue

        if "Network" in line and ":" in line:
            parts = line.split(":", 1)
            if len(parts) > 1:
                current["network"] = parts[1].strip()
        elif "Gateway" in line and ":" in line:
            parts = line.split(":", 1)
            if len(parts) > 1:
                current["gateway"] = parts[1].strip()
        elif "Mask" in line and ":" in line:
            parts = line.split(":", 1)
            if len(parts) > 1:
                current["mask"] = parts[1].strip()
        elif "Lease" in line and ":" in line:
            parts = line.split(":", 1)
            if len(parts) > 1:
                current["lease"] = parts[1].strip()

    if current:
        pools.append(_build_pool(current))

    return pools


def _build_pool(data: dict[str, str]) -> DhcpPoolInfo:
    """从解析字典构建 DhcpPoolInfo。"""
    return DhcpPoolInfo(
        name=data.get("name", ""),
        network=data.get("network", ""),
        gateway=data.get("gateway", ""),
        mask=data.get("mask"),
        lease=data.get("lease"),
    )


def parse_dhcp_statistics(output: str) -> Optional[bool]:
    """解析 display dhcp statistics 输出，返回 DHCP 是否启用。"""
    if "DHCP is not enabled" in output:
        return False
    if "DHCP server statistic" in output:
        return True
    return None


def parse_vlanifs_from_config(config_output: str) -> list[VlanifInfo]:
    """从 display current-configuration 输出中解析 Vlanif 接口配置。"""
    vlanifs: list[VlanifInfo] = []
    current_vlanif: Optional[int] = None
    current_ip: Optional[str] = None
    current_mask: Optional[str] = None
    current_dhcp: Optional[str] = None

    for line in config_output.splitlines():
        stripped = line.strip()

        # 匹配 interface VlanifXX
        m = re.match(r"interface Vlanif(\d+)", stripped)
        if m:
            # 保存上一个 Vlanif
            if current_vlanif is not None:
                vlanifs.append(VlanifInfo(
                    vlan_id=current_vlanif,
                    ip_address=current_ip,
                    subnet_mask=current_mask,
                    dhcp_select=current_dhcp,
                ))
            current_vlanif = int(m.group(1))
            current_ip = None
            current_mask = None
            current_dhcp = None
            continue

        if current_vlanif is not None:
            # 匹配 ip address X.X.X.X Y.Y.Y.Y
            m = re.match(r"ip address (\S+) (\S+)", stripped)
            if m:
                current_ip = m.group(1)
                current_mask = m.group(2)
                continue

            # 匹配 dhcp select global/interface
            m = re.match(r"dhcp select (\S+)", stripped)
            if m:
                current_dhcp = m.group(1)
                continue

            # 遇到非 Vlanif 子命令，结束当前 Vlanif
            if stripped and not stripped.startswith("#"):
                # 可能是其他 interface 或 return
                if re.match(r"interface |return", stripped):
                    if current_vlanif is not None:
                        vlanifs.append(VlanifInfo(
                            vlan_id=current_vlanif,
                            ip_address=current_ip,
                            subnet_mask=current_mask,
                            dhcp_select=current_dhcp,
                        ))
                    current_vlanif = None

    # 最后一个 Vlanif
    if current_vlanif is not None:
        vlanifs.append(VlanifInfo(
            vlan_id=current_vlanif,
            ip_address=current_ip,
            subnet_mask=current_mask,
            dhcp_select=current_dhcp,
        ))

    return vlanifs


def parse_dhcp_pools_from_config(config_output: str) -> list[DhcpPoolInfo]:
    """从 display current-configuration 输出中解析 DHCP 地址池配置。"""
    pools: list[DhcpPoolInfo] = []
    current_pool: Optional[str] = None
    current_network: Optional[str] = None
    current_gateway: Optional[str] = None
    current_mask: Optional[str] = None

    for line in config_output.splitlines():
        stripped = line.strip()

        # 匹配 ip pool XXXX
        m = re.match(r"ip pool (\S+)", stripped)
        if m:
            # 保存上一个 pool
            if current_pool is not None:
                pools.append(DhcpPoolInfo(
                    name=current_pool,
                    network=current_network or "",
                    gateway=current_gateway or "",
                    mask=current_mask,
                ))
            current_pool = m.group(1)
            current_network = None
            current_gateway = None
            current_mask = None
            continue

        if current_pool is not None:
            m = re.match(r"network (\S+) mask (\S+)", stripped)
            if m:
                current_network = m.group(1)
                current_mask = m.group(2)
                continue

            m = re.match(r"gateway-list (\S+)", stripped)
            if m:
                current_gateway = m.group(1)
                continue

            # 遇到非 pool 子命令
            if stripped and not stripped.startswith("#"):
                if re.match(r"ip pool |return|interface |vlan", stripped):
                    if current_pool is not None:
                        pools.append(DhcpPoolInfo(
                            name=current_pool,
                            network=current_network or "",
                            gateway=current_gateway or "",
                            mask=current_mask,
                        ))
                    current_pool = None

    # 最后一个 pool
    if current_pool is not None:
        pools.append(DhcpPoolInfo(
            name=current_pool,
            network=current_network or "",
            gateway=current_gateway or "",
            mask=current_mask,
        ))

    return pools


def _abbreviate_interface(name: str) -> str:
    """将完整接口名缩写为华为 VRP 短格式。

    GigabitEthernet0/0/1 → GE0/0/1
    Ethernet0/0/0 → Ethernet0/0/0（不变）
    """
    if name.startswith("GigabitEthernet"):
        return "GE" + name[len("GigabitEthernet"):]
    return name


def _parse_access_ports_from_config(
    config_output: str, device_name: str,
) -> dict[str, int]:
    """从 display current-configuration 中解析 access 端口 VLAN 分配。"""
    access_ports: dict[str, int] = {}
    current_iface: Optional[str] = None
    current_vlan: Optional[int] = None

    for line in config_output.splitlines():
        stripped = line.strip()

        m = re.match(r"interface (\S+)", stripped)
        if m:
            # 保存上一个接口
            if current_iface and current_vlan is not None:
                access_ports[current_iface] = current_vlan
            current_iface = m.group(1)
            current_vlan = None
            continue

        if current_iface:
            m = re.match(r"port default vlan (\d+)", stripped)
            if m:
                current_vlan = int(m.group(1))
                continue

            if stripped and not stripped.startswith("#"):
                if re.match(r"interface |return", stripped):
                    if current_iface and current_vlan is not None:
                        access_ports[current_iface] = current_vlan
                    current_iface = None

    if current_iface and current_vlan is not None:
        access_ports[current_iface] = current_vlan

    return access_ports


def _parse_trunk_ports_from_config(
    config_output: str, device_name: str,
) -> dict[str, list[int]]:
    """从 display current-configuration 中解析 trunk 端口允许的 VLAN。"""
    trunk_ports: dict[str, list[int]] = {}
    current_iface: Optional[str] = None
    is_trunk = False
    allowed_vlans: list[int] = []

    for line in config_output.splitlines():
        stripped = line.strip()

        m = re.match(r"interface (\S+)", stripped)
        if m:
            # 保存上一个接口
            if current_iface and is_trunk and allowed_vlans:
                trunk_ports[_abbreviate_interface(current_iface)] = allowed_vlans
            current_iface = m.group(1)
            is_trunk = False
            allowed_vlans = []
            continue

        if current_iface:
            if stripped == "port link-type trunk":
                is_trunk = True
                continue

            m = re.match(r"port trunk allow-pass vlan (.+)", stripped)
            if m:
                vlan_str = m.group(1).strip()
                allowed_vlans = [int(v) for v in vlan_str.split() if v.isdigit()]
                continue

            if stripped and not stripped.startswith("#"):
                if re.match(r"interface |return", stripped):
                    if current_iface and is_trunk and allowed_vlans:
                        trunk_ports[_abbreviate_interface(current_iface)] = allowed_vlans
                    current_iface = None

    if current_iface and is_trunk and allowed_vlans:
        trunk_ports[_abbreviate_interface(current_iface)] = allowed_vlans

    return trunk_ports


# --- 分析逻辑 ---

def _classify_device(name: str) -> str:
    """判断设备是 L3 还是 L2 交换机。"""
    return "l3_switch" if name in _L3_SWITCHES else "l2_switch"


def analyze_dhcp_config(
    diagnostics: list[DeviceDiagnostics],
) -> DhcpAnalysis:
    """分析 DHCP 地址分发配置状态。

    检查每台交换机是否：
    1. 创建了预期的 VLAN
    2. L3 交换机：配置了 Vlanif IP、DHCP enable、地址池
    3. L2 交换机：access 端口分配了正确的 VLAN，trunk 端口允许预期 VLAN

    Args:
        diagnostics: LSW1-LSW4 的诊断数据列表

    Returns:
        结构化的 DHCP 分析结果
    """
    result = DhcpAnalysis()
    diag_map = {d.device_name: d for d in diagnostics}

    all_vlans_ok = True
    all_vlanifs_ok = True
    all_dhcp_ok = True
    all_ports_ok = True

    for device_name in _EXPECTED_DHCP_VLANS:
        diag = diag_map.get(device_name)
        dev_type = _classify_device(device_name)
        analysis = DhcpSwitchAnalysis(
            device_name=device_name,
            device_type=dev_type,
        )

        if not diag:
            analysis.issues.append("无诊断数据")
            result.device_analyses.append(analysis)
            result.gaps.append(f"[{device_name}] 无诊断数据")
            all_vlans_ok = False
            continue

        # 1. 解析 VLAN
        vlan_output = _get_command_output(diag, "display vlan")
        vlans = parse_vlan(vlan_output) if vlan_output else []
        vlan_ids = {v.vlan_id for v in vlans}
        analysis.vlans = sorted(vlan_ids)

        expected_vlans = _EXPECTED_DHCP_VLANS.get(device_name, [])
        for vid in expected_vlans:
            if vid not in vlan_ids:
                analysis.issues.append(f"缺少 VLAN {vid}")
                all_vlans_ok = False

        # 2. 解析 current-configuration（用于 Vlanif、pool、端口配置）
        config_output = _get_command_output(diag, "display current-configuration")

        if dev_type == "l3_switch":
            # 2a. 检查 Vlanif
            if config_output:
                vlanifs = parse_vlanifs_from_config(config_output)
                analysis.vlanifs = vlanifs
                vlanif_map = {v.vlan_id: v for v in vlanifs}

                expected_vlanifs = _EXPECTED_VLANIFS.get(device_name, {})
                for vid, expected_ip in expected_vlanifs.items():
                    vif = vlanif_map.get(vid)
                    if not vif:
                        analysis.issues.append(f"缺少 Vlanif{vid}")
                        all_vlanifs_ok = False
                    elif vif.ip_address != expected_ip:
                        analysis.issues.append(
                            f"Vlanif{vid} IP {vif.ip_address}，预期 {expected_ip}"
                        )
                        all_vlanifs_ok = False
                    elif vif.dhcp_select != "global":
                        analysis.issues.append(
                            f"Vlanif{vid} dhcp select 为 {vif.dhcp_select}，预期 global"
                        )
                        all_dhcp_ok = False

            # 2b. 检查 DHCP enable（从 statistics 判断）
            stats_output = _get_command_output(diag, "display dhcp statistics")
            if stats_output:
                dhcp_enabled = parse_dhcp_statistics(stats_output)
                analysis.dhcp_enabled = dhcp_enabled
                if dhcp_enabled is False:
                    analysis.issues.append("DHCP 未启用")
                    all_dhcp_ok = False

            # 2c. 检查地址池
            pool_output = _get_command_output(diag, "display ip pool")
            if pool_output and "No IP pool found" not in pool_output:
                pools = parse_ip_pool(pool_output)
                analysis.dhcp_pools = pools
                pool_names = {p.name for p in pools}
                expected_pools = _EXPECTED_POOLS.get(device_name, {})
                for pool_name in expected_pools:
                    if pool_name not in pool_names:
                        analysis.issues.append(f"缺少地址池 {pool_name}")
                        all_dhcp_ok = False

            # 2d. 检查 trunk 端口
            if config_output:
                trunk_ports = _parse_trunk_ports_from_config(config_output, device_name)
                analysis.trunk_ports = trunk_ports
                expected_trunks = _EXPECTED_TRUNK_PORTS.get(device_name, {})
                for port, expected_vids in expected_trunks.items():
                    actual_vids = trunk_ports.get(port, [])
                    if sorted(actual_vids) != sorted(expected_vids):
                        analysis.issues.append(
                            f"{port} trunk 允许 VLAN {actual_vids}，预期 {expected_vids}"
                        )
                        all_ports_ok = False

        else:
            # L2 交换机
            if config_output:
                # 2e. 检查 access 端口
                access_ports = _parse_access_ports_from_config(config_output, device_name)
                analysis.access_ports = access_ports
                expected_access = _EXPECTED_ACCESS_PORTS.get(device_name, {})
                for port, expected_vid in expected_access.items():
                    actual_vid = access_ports.get(port)
                    if actual_vid != expected_vid:
                        analysis.issues.append(
                            f"{port} access VLAN {actual_vid}，预期 {expected_vid}"
                        )
                        all_ports_ok = False

                # 2f. 检查 trunk 端口
                trunk_ports = _parse_trunk_ports_from_config(config_output, device_name)
                analysis.trunk_ports = trunk_ports
                expected_trunks = _EXPECTED_TRUNK_PORTS.get(device_name, {})
                for port, expected_vids in expected_trunks.items():
                    actual_vids = trunk_ports.get(port, [])
                    if sorted(actual_vids) != sorted(expected_vids):
                        analysis.issues.append(
                            f"{port} trunk 允许 VLAN {actual_vids}，预期 {expected_vids}"
                        )
                        all_ports_ok = False

        result.device_analyses.append(analysis)

    result.all_vlans_configured = all_vlans_ok
    result.all_vlanifs_configured = all_vlanifs_ok
    result.dhcp_fully_configured = all_dhcp_ok
    result.all_ports_correct = all_ports_ok

    # 汇总 gaps
    for da in result.device_analyses:
        for issue in da.issues:
            result.gaps.append(f"[{da.device_name}] {issue}")

    # 生成配置建议
    if result.gaps:
        result.config_suggestions = _generate_dhcp_config_suggestions(
            result.device_analyses, result.gaps
        )

    return result


def _generate_dhcp_config_suggestions(
    analyses: list[DhcpSwitchAnalysis],
    gaps: list[str],
) -> list[str]:
    """根据 DHCP 分析缺口生成配置建议。"""
    suggestions = []
    warning = "[仅建议，不执行]"

    for gap in gaps:
        if "缺少 VLAN" in gap:
            device = gap.split("]")[0].strip("[")
            expected = _EXPECTED_DHCP_VLANS.get(device, [])
            if expected:
                vlan_str = " ".join(str(v) for v in expected)
                suggestions.append(
                    f"{warning} [{device}] 建议创建 VLAN:\n"
                    f"  system-view\n"
                    f"  vlan batch {vlan_str}"
                )
        elif "缺少 Vlanif" in gap:
            device = gap.split("]")[0].strip("[")
            m = re.search(r"Vlanif(\d+)", gap)
            if m:
                vid = int(m.group(1))
                expected_ip = _EXPECTED_VLANIFS.get(device, {}).get(vid, "")
                suggestions.append(
                    f"{warning} [{device}] 建议创建 Vlanif{vid}:\n"
                    f"  system-view\n"
                    f"  interface Vlanif{vid}\n"
                    f"  ip address {expected_ip} 255.255.255.0\n"
                    f"  dhcp select global"
                )
        elif "DHCP 未启用" in gap:
            device = gap.split("]")[0].strip("[")
            suggestions.append(
                f"{warning} [{device}] 建议启用 DHCP:\n"
                f"  system-view\n"
                f"  dhcp enable"
            )
        elif "缺少地址池" in gap:
            device = gap.split("]")[0].strip("[")
            m = re.search(r"地址池 (\S+)", gap)
            if m:
                pool_name = m.group(1)
                pool_info = _EXPECTED_POOLS.get(device, {}).get(pool_name, "")
                if pool_info:
                    # 从 network 推导 gateway（最后一个 .0 改为 .1）
                    gateway = pool_info.rsplit(".", 1)[0] + ".1"
                    suggestions.append(
                        f"{warning} [{device}] 建议创建地址池 {pool_name}:\n"
                        f"  system-view\n"
                        f"  ip pool {pool_name}\n"
                        f"  network {pool_info} mask 255.255.255.0\n"
                        f"  gateway-list {gateway}"
                    )
        elif "access VLAN" in gap:
            suggestions.append(
                f"{warning} 端口 access VLAN 不正确: {gap}"
            )
        elif "trunk 允许 VLAN" in gap:
            suggestions.append(
                f"{warning} trunk 端口 VLAN 配置不正确: {gap}"
            )

    return suggestions
