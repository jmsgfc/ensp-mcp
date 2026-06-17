"""DHCP 最终验证服务。

在交换机侧 DHCP 配置下发成功后，验证 PC1/2/3/4 是否真正通过 DHCP 获取了 IP 地址。

验证维度：
1. DHCP 状态（是否处于已获取地址状态）
2. IP 地址（是否存在于预期子网内）
3. 子网掩码（是否与预期一致）
4. 默认网关（是否与预期一致）

最小版本策略：
- Mock 模式：完整验证 PC1/2/3/4 的 DHCP 结果
- 真实 eNSP 模式：明确标注"交换机侧已验证，PC 侧自动读取待后续实现"
"""

import ipaddress
from dataclasses import dataclass, field
from typing import Optional

from backend.adapters.base_adapter import BaseAdapter, DeviceDiagnostics
from backend.services.dhcp_analysis import analyze_dhcp_config


# --- 数据模型 ---

@dataclass
class PcDhcpVerification:
    """单台 PC 的 DHCP 验证结果。"""
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
    status: str = "unknown"
    # status 取值：
    #   "success"        — DHCP 已获取、IP 在子网内、掩码正确、网关正确
    #   "no_ip"          — DHCP 未获取到 IP（dhcp_state=0 或 ip=None）
    #   "wrong_subnet"   — IP 不在预期子网内
    #   "wrong_mask"     — 掩码与预期不一致
    #   "wrong_gateway"  — 网关与预期不一致
    #   "unavailable"    — PC 数据不可读（适配器不支持或显式不可用）


@dataclass
class DhcpFinalReport:
    """DHCP 最终验证报告。"""
    available: bool  # PC 数据是否可读（全部 PC 均可读时为 True）
    verification_mode: str  # "mock" / "topo_file" / "unavailable"
    pc_results: list[PcDhcpVerification] = field(default_factory=list)
    all_success: bool = False
    summary: str = ""
    note: Optional[str] = None


# --- 预期地址规划 ---

_EXPECTED_PC_CONFIG: dict[str, dict] = {
    "PC1": {
        "vlan": 10,
        "subnet": "192.168.10.0/24",
        "mask": "255.255.255.0",
        "gateway": "192.168.10.1",
    },
    "PC2": {
        "vlan": 20,
        "subnet": "192.168.20.0/24",
        "mask": "255.255.255.0",
        "gateway": "192.168.20.1",
    },
    "PC3": {
        "vlan": 30,
        "subnet": "192.168.30.0/24",
        "mask": "255.255.255.0",
        "gateway": "192.168.30.1",
    },
    "PC4": {
        "vlan": 40,
        "subnet": "192.168.40.0/24",
        "mask": "255.255.255.0",
        "gateway": "192.168.40.1",
    },
}


# --- 辅助函数 ---

def _check_ip_in_subnet(ip_str: str, subnet_str: str) -> bool:
    """检查 IP 是否在指定子网内。"""
    try:
        ip = ipaddress.ip_address(ip_str)
        network = ipaddress.ip_network(subnet_str, strict=False)
        return ip in network
    except ValueError:
        return False


# --- 主函数 ---

def verify_dhcp_result(
    adapter: BaseAdapter,
    diagnostics: list[DeviceDiagnostics],
) -> DhcpFinalReport:
    """验证 DHCP 配置下发后的最终结果。

    流程：
    1. 检查交换机侧 DHCP 配置是否完成
    2. 对 PC1/2/3/4 逐一查询 DHCP 状态
    3. 逐项验证：dhcp_state → IP 子网 → 掩码 → 网关
    4. 聚合汇总（不被单台 PC 状态覆盖）

    Args:
        adapter: 设备适配器
        diagnostics: 交换机诊断数据列表

    Returns:
        DhcpFinalReport 结构化验证报告
    """
    # 1. 检查交换机侧状态
    dhcp_analysis = analyze_dhcp_config(diagnostics)
    if not dhcp_analysis.dhcp_fully_configured:
        return DhcpFinalReport(
            available=False,
            verification_mode="unavailable",
            note="交换机侧 DHCP 未完成，无法验证 PC 结果",
            summary="交换机侧 DHCP 配置未完成",
        )

    # 2. 逐一查询 PC 状态
    pc_results: list[PcDhcpVerification] = []
    has_unavailable = False
    has_failure = False
    all_pc_success = True

    for pc_name, expected in _EXPECTED_PC_CONFIG.items():
        result = _verify_single_pc(adapter, pc_name, expected)
        pc_results.append(result)

        if result.status == "unavailable":
            has_unavailable = True
            all_pc_success = False
        elif result.status != "success":
            has_failure = True
            all_pc_success = False

    # 3. 聚合（不被循环覆盖）
    total = len(pc_results)
    success_count = sum(1 for r in pc_results if r.status == "success")

    # available：全部 PC 均可读时为 True
    all_available = not has_unavailable

    # verification_mode：稳定聚合
    if has_unavailable:
        verification_mode = "unavailable"
    else:
        verification_mode = "mock"

    # summary
    if all_pc_success and total == len(_EXPECTED_PC_CONFIG):
        summary = f"全部 {total} 台 PC 已通过 DHCP 获取到正确地址（IP/掩码/网关均正确）"
    elif success_count > 0:
        failed_names = [r.pc_name for r in pc_results if r.status != "success"]
        summary = f"{success_count}/{total} 台 PC 验证通过，{', '.join(failed_names)} 未通过"
    elif has_unavailable:
        summary = "交换机侧已验证，PC 侧自动读取待后续实现"
    else:
        summary = "全部 PC 验证未通过"

    note = None
    if has_unavailable:
        note = "交换机侧已验证，PC 侧自动读取待后续实现"

    return DhcpFinalReport(
        available=all_available,
        verification_mode=verification_mode,
        pc_results=pc_results,
        all_success=all_pc_success and total == len(_EXPECTED_PC_CONFIG),
        summary=summary,
        note=note,
    )


def _verify_single_pc(
    adapter: BaseAdapter,
    pc_name: str,
    expected: dict,
) -> PcDhcpVerification:
    """验证单台 PC 的 DHCP 状态。

    按优先级判定 status：
    1. unavailable — 适配器不支持或显式不可用
    2. no_ip — DHCP 未获取到 IP
    3. wrong_subnet — IP 不在预期子网
    4. wrong_mask — 掩码不正确
    5. wrong_gateway — 网关不正确
    6. success — 全部通过
    """
    # 查询 PC 状态
    try:
        status = adapter.get_pc_dhcp_status(pc_name)
    except NotImplementedError:
        return PcDhcpVerification(
            pc_name=pc_name,
            expected_vlan=expected["vlan"],
            expected_subnet=expected["subnet"],
            expected_mask=expected["mask"],
            expected_gateway=expected["gateway"],
            status="unavailable",
        )

    if not status.available:
        return PcDhcpVerification(
            pc_name=pc_name,
            expected_vlan=expected["vlan"],
            expected_subnet=expected["subnet"],
            expected_mask=expected["mask"],
            expected_gateway=expected["gateway"],
            status="unavailable",
        )

    dhcp_enabled = status.dhcp_state == 1

    # DHCP 未获取到 IP
    if status.ip_address is None or not dhcp_enabled:
        return PcDhcpVerification(
            pc_name=pc_name,
            expected_vlan=expected["vlan"],
            expected_subnet=expected["subnet"],
            expected_mask=expected["mask"],
            expected_gateway=expected["gateway"],
            actual_ip=status.ip_address,
            actual_mask=status.mask,
            actual_gateway=status.gateway,
            dhcp_enabled=dhcp_enabled,
            status="no_ip",
        )

    # IP 子网检查
    in_subnet = _check_ip_in_subnet(status.ip_address, expected["subnet"])

    # 掩码检查
    mask_ok = status.mask == expected["mask"]

    # 网关检查
    gateway_ok = status.gateway == expected["gateway"]

    # 判定最终 status（按优先级）
    if not in_subnet:
        final_status = "wrong_subnet"
    elif not mask_ok:
        final_status = "wrong_mask"
    elif not gateway_ok:
        final_status = "wrong_gateway"
    else:
        final_status = "success"

    return PcDhcpVerification(
        pc_name=pc_name,
        expected_vlan=expected["vlan"],
        expected_subnet=expected["subnet"],
        expected_mask=expected["mask"],
        expected_gateway=expected["gateway"],
        actual_ip=status.ip_address,
        actual_mask=status.mask,
        actual_gateway=status.gateway,
        ip_in_expected_subnet=in_subnet,
        mask_ok=mask_ok,
        gateway_ok=gateway_ok,
        dhcp_enabled=dhcp_enabled,
        status=final_status,
    )
