"""Campus VRRP/MSTP/DHCP/Easy NAT lab automation.

This module intentionally reads the active .topo file at execution time and
uses the device com_port values from that file. That keeps configuration scoped
to the topology currently opened by the user instead of any stale inventory.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from backend.adapters.telnet_client import (
    TelnetClient,
    TelnetCommandError,
    TelnetConfig,
    TelnetConnectionError,
)
from backend.topology.config import get_topology_path
from backend.topology.models import DeviceTopoInfo, LinkInfo
from backend.topology.interface_mapping import interface_name
from backend.topology.parser import parse_topology


ERROR_MARKERS = (
    "Error:",
    "Wrong parameter",
    "Incomplete command",
    "Unrecognized command",
)

IDEMPOTENT_MESSAGES = (
    "already exists",
    "already exist",
    "has been configed",
    "has already exist",
    "Please delete the network section first",
    "Please delete all sections of the pool before modifying",
    "Some of addresses not be excluded are not idle",
    "Part of the domain-name-server IP has already exist",
    "Part of the gateway IP has already exist",
    "The primary address does not exist",
    "The IP address does not exist",
)


@dataclass(frozen=True)
class RuntimeDevice:
    name: str
    model: str
    port: int
    device_type: str


def _device_type(model: str) -> str:
    if model.upper() == "PC":
        return "pc"
    if model.upper().startswith("AR"):
        return "router"
    return "switch"


def _load_current_topology() -> tuple[dict[str, DeviceTopoInfo], list[LinkInfo]]:
    topo = parse_topology(get_topology_path())
    return {device.name: device for device in topo.devices}, topo.links


def _runtime_devices(devices: dict[str, DeviceTopoInfo]) -> dict[str, RuntimeDevice]:
    runtime: dict[str, RuntimeDevice] = {}
    for name, device in devices.items():
        runtime[name] = RuntimeDevice(
            name=name,
            model=device.model,
            port=device.com_port,
            device_type=_device_type(device.model),
        )
    return runtime


def _safe_topology_value() -> str | None:
    try:
        return str(get_topology_path())
    except (FileNotFoundError, RuntimeError):
        return None


def _find_link_port(
    devices: dict[str, DeviceTopoInfo],
    links: list[LinkInfo],
    device_name: str,
    peer_name: str,
) -> str:
    device = devices[device_name]
    peer = devices[peer_name]
    for link in links:
        if link.src_device_id == device.id and link.dest_device_id == peer.id:
            return interface_name(device, link.src_index)
        if link.dest_device_id == device.id and link.src_device_id == peer.id:
            return interface_name(device, link.tar_index)
    raise ValueError(f"current topology has no link {device_name} <-> {peer_name}")


def _has_command_error(output: str) -> bool:
    if any(message in output for message in IDEMPOTENT_MESSAGES):
        return False
    return any(marker in output for marker in ERROR_MARKERS)


def _connect(port: int, timeout: float = 15.0) -> TelnetClient:
    client = TelnetClient(TelnetConfig("127.0.0.1", port, timeout=timeout))
    client.connect()
    return client


def _run_lines(port: int, lines: list[str]) -> dict[str, Any]:
    client = _connect(port)
    command_results: list[dict[str, Any]] = []
    try:
        try:
            client.send_command("return", timeout=5.0)
        except (TelnetConnectionError, TelnetCommandError):
            pass
        for line in lines:
            if not line.strip():
                continue
            command = line.strip()
            try:
                output = client.send_command(command, timeout=30.0)
                command_results.append({
                    "command": command,
                    "success": not _has_command_error(output),
                    "output": output,
                })
            except (TelnetConnectionError, TelnetCommandError) as exc:
                command_results.append({
                    "command": command,
                    "success": False,
                    "error": str(exc),
                })
                break
    finally:
        client.close()

    errors = [
        {
            "command": item["command"],
            "detail": item.get("error") or "\n".join(
                line.strip()
                for line in str(item.get("output", "")).splitlines()
                if _has_command_error(line)
            ),
        }
        for item in command_results
        if not item.get("success", False)
    ]
    return {
        "success": not errors,
        "commands": command_results,
        "errors": errors,
    }


def _run_command(port: int, command: str, timeout: float = 12.0) -> str:
    client = _connect(port, timeout=max(timeout, 12.0))
    try:
        return client.send_command(command, timeout=timeout)
    finally:
        client.close()


def _save_device(device: RuntimeDevice) -> dict[str, Any]:
    client = _connect(device.port, timeout=15.0)
    try:
        output = client.send_save_command(
            device.device_type,
            device.name,
            timeout=45.0,
        )
    except (TelnetConnectionError, TelnetCommandError) as exc:
        return {"device": device.name, "success": False, "error": str(exc)}
    finally:
        client.close()
    success = "successfully" in output.lower() or "saved successfully" in output.lower()
    return {"device": device.name, "success": success, "output": output}


def _config_lines(devices: dict[str, DeviceTopoInfo], links: list[LinkInfo]) -> dict[str, list[str]]:
    lsw1_ar2 = _find_link_port(devices, links, "LSW1", "AR2")
    lsw1_lsw2 = _find_link_port(devices, links, "LSW1", "LSW2")
    lsw1_lsw3 = _find_link_port(devices, links, "LSW1", "LSW3")
    lsw1_lsw4 = _find_link_port(devices, links, "LSW1", "LSW4")
    lsw4_ar2 = _find_link_port(devices, links, "LSW4", "AR2")
    lsw4_lsw2 = _find_link_port(devices, links, "LSW4", "LSW2")
    lsw4_lsw3 = _find_link_port(devices, links, "LSW4", "LSW3")
    lsw4_lsw1 = _find_link_port(devices, links, "LSW4", "LSW1")
    lsw2_pc1 = _find_link_port(devices, links, "LSW2", "PC1")
    lsw2_pc2 = _find_link_port(devices, links, "LSW2", "PC2")
    lsw2_lsw1 = _find_link_port(devices, links, "LSW2", "LSW1")
    lsw2_lsw4 = _find_link_port(devices, links, "LSW2", "LSW4")
    lsw3_pc3 = _find_link_port(devices, links, "LSW3", "PC3")
    lsw3_pc4 = _find_link_port(devices, links, "LSW3", "PC4")
    lsw3_lsw1 = _find_link_port(devices, links, "LSW3", "LSW1")
    lsw3_lsw4 = _find_link_port(devices, links, "LSW3", "LSW4")
    ar2_internet = _find_link_port(devices, links, "AR2", "internet")
    ar2_lsw1 = _find_link_port(devices, links, "AR2", "LSW1")
    ar2_lsw4 = _find_link_port(devices, links, "AR2", "LSW4")
    internet_ar2 = _find_link_port(devices, links, "internet", "AR2")
    internet_pc5 = _find_link_port(devices, links, "internet", "PC5")

    common_mstp = [
        "stp mode mstp",
        "stp region-configuration",
        "region-name CAMPUS",
        "revision-level 1",
        "instance 1 vlan 10 30",
        "instance 2 vlan 20 40",
        "active region-configuration",
        "quit",
    ]

    return {
        "LSW1": [
            "system-view", "sysname LSW1", "vlan batch 10 20 30 40 50 80", *common_mstp,
            "stp instance 1 root primary", "stp instance 2 root secondary", "dhcp enable",
            *(_vlanif("10", "192.168.10.252", "120")),
            *(_vlanif("20", "192.168.20.252", "100")),
            *(_vlanif("30", "192.168.30.252", "120")),
            *(_vlanif("40", "192.168.40.252", "100")),
            "interface Vlanif50", "ip address 192.168.50.2 255.255.255.252", "quit",
            *_access_port(lsw1_ar2, "50"),
            *_trunk_port(lsw1_lsw2), *_trunk_port(lsw1_lsw3), *_trunk_port(lsw1_lsw4),
            *_dhcp_pool("10", high_exclude=True), *_dhcp_pool("20", high_exclude=True),
            *_dhcp_pool("30", high_exclude=True), *_dhcp_pool("40", high_exclude=True),
            "ip route-static 0.0.0.0 0.0.0.0 192.168.50.1", "return",
        ],
        "LSW4": [
            "system-view", "sysname LSW4", "vlan batch 10 20 30 40 50 80", *common_mstp,
            "stp instance 1 root secondary", "stp instance 2 root primary", "dhcp enable",
            *(_vlanif("10", "192.168.10.253", "100")),
            *(_vlanif("20", "192.168.20.253", "120")),
            *(_vlanif("30", "192.168.30.253", "100")),
            *(_vlanif("40", "192.168.40.253", "120")),
            "interface Vlanif80", "ip address 192.168.80.2 255.255.255.252", "quit",
            *_access_port(lsw4_ar2, "80"),
            *_trunk_port(lsw4_lsw2), *_trunk_port(lsw4_lsw3), *_trunk_port(lsw4_lsw1),
            *_dhcp_pool("10", high_exclude=False), *_dhcp_pool("20", high_exclude=False),
            *_dhcp_pool("30", high_exclude=False), *_dhcp_pool("40", high_exclude=False),
            "ip route-static 0.0.0.0 0.0.0.0 192.168.80.1", "return",
        ],
        "LSW2": [
            "system-view", "sysname LSW2", "vlan batch 10 20 30 40", *common_mstp,
            *_access_port(lsw2_pc1, "10", edge=True), *_access_port(lsw2_pc2, "20", edge=True),
            *_trunk_port(lsw2_lsw1), *_trunk_port(lsw2_lsw4), "return",
        ],
        "LSW3": [
            "system-view", "sysname LSW3", "vlan batch 10 20 30 40", *common_mstp,
            *_access_port(lsw3_pc3, "30", edge=True), *_access_port(lsw3_pc4, "40", edge=True),
            *_trunk_port(lsw3_lsw1), *_trunk_port(lsw3_lsw4), "return",
        ],
        "AR2": [
            "system-view", "sysname AR2", "acl number 2000",
            "rule 5 permit source 192.168.10.0 0.0.0.255",
            "rule 10 permit source 192.168.20.0 0.0.0.255",
            "rule 15 permit source 192.168.30.0 0.0.0.255",
            "rule 20 permit source 192.168.40.0 0.0.0.255", "quit",
            f"interface {ar2_internet}", "undo ip address", "ip address 120.36.2.1 255.255.255.252", "nat outbound 2000", "quit",
            f"interface {ar2_lsw1}", "undo ip address", "ip address 192.168.50.1 255.255.255.252", "quit",
            f"interface {ar2_lsw4}", "undo ip address", "ip address 192.168.80.1 255.255.255.252", "quit",
            "ip route-static 192.168.10.0 255.255.255.0 192.168.50.2",
            "ip route-static 192.168.30.0 255.255.255.0 192.168.50.2",
            "ip route-static 192.168.20.0 255.255.255.0 192.168.80.2",
            "ip route-static 192.168.40.0 255.255.255.0 192.168.80.2",
            "ip route-static 0.0.0.0 0.0.0.0 120.36.2.2", "return",
        ],
        "internet": [
            "system-view", "sysname internet",
            f"interface {internet_ar2}", "undo ip address", "ip address 120.36.2.2 255.255.255.252", "quit",
            f"interface {internet_pc5}", "undo ip address", "ip address 8.8.8.254 255.255.255.0", "quit",
            "ip route-static 192.168.50.0 255.255.255.252 120.36.2.1",
            "ip route-static 192.168.80.0 255.255.255.252 120.36.2.1", "return",
        ],
    }


def _access_port(interface: str, vlan: str, edge: bool = False) -> list[str]:
    lines = ["interface " + interface, "port link-type access", f"port default vlan {vlan}"]
    if edge:
        lines.append("stp edged-port enable")
    lines.append("quit")
    return lines


def _trunk_port(interface: str) -> list[str]:
    return [
        "interface " + interface,
        "port link-type trunk",
        "port trunk allow-pass vlan 10 20 30 40",
        "quit",
    ]


def _vlanif(vlan: str, ip: str, priority: str) -> list[str]:
    lines = [
        f"interface Vlanif{vlan}",
        f"ip address {ip} 255.255.255.0",
        f"vrrp vrid {vlan} virtual-ip 192.168.{vlan}.254",
        f"vrrp vrid {vlan} priority {priority}",
    ]
    if priority == "120":
        lines.append(f"vrrp vrid {vlan} preempt-mode timer delay 20")
    lines.extend(["dhcp select global", "quit"])
    return lines


def _dhcp_pool(vlan: str, high_exclude: bool) -> list[str]:
    lines = [
        f"ip pool VLAN{vlan}",
        f"gateway-list 192.168.{vlan}.254",
        f"network 192.168.{vlan}.0 mask 255.255.255.0",
    ]
    if high_exclude:
        lines.append(f"excluded-ip-address 192.168.{vlan}.100 192.168.{vlan}.253")
    else:
        lines.append(f"excluded-ip-address 192.168.{vlan}.1 192.168.{vlan}.99")
        lines.append(f"excluded-ip-address 192.168.{vlan}.252 192.168.{vlan}.253")
    lines.extend(["dns-list 8.8.8.8", "quit"])
    return lines


def plan_campus_lab() -> dict[str, Any]:
    devices, links = _load_current_topology()
    runtime = _runtime_devices(devices)
    required = ["LSW1", "LSW2", "LSW3", "LSW4", "AR2", "internet", "PC1", "PC2", "PC3", "PC4", "PC5"]
    missing = [name for name in required if name not in devices]
    if missing:
        return {"success": False, "topology": str(get_topology_path()), "missing_devices": missing}
    configs = _config_lines(devices, links)
    return {
        "success": True,
        "topology": str(get_topology_path()),
        "devices": {name: runtime[name].__dict__ for name in configs},
        "command_count": {name: len(lines) for name, lines in configs.items()},
        "summary": {
            "vrrp_master": {"LSW1": ["VLAN10", "VLAN30"], "LSW4": ["VLAN20", "VLAN40"]},
            "mstp": {"instance_1": "VLAN10,VLAN30 root LSW1", "instance_2": "VLAN20,VLAN40 root LSW4"},
            "nat": "AR2 GE toward internet uses EasyIP NAT with ACL 2000",
        },
    }


def apply_campus_lab() -> dict[str, Any]:
    devices, links = _load_current_topology()
    runtime = _runtime_devices(devices)
    configs = _config_lines(devices, links)
    results = {}
    for name in ["internet", "AR2", "LSW1", "LSW4", "LSW2", "LSW3"]:
        if runtime[name].port <= 0:
            results[name] = {"success": False, "errors": ["device has no Telnet com_port"]}
            continue
        results[name] = _run_lines(runtime[name].port, configs[name])
    return {
        "success": all(result.get("success") for result in results.values()),
        "topology": str(get_topology_path()),
        "results": results,
    }


def _ping_ok(output: str) -> bool:
    text = output.lower()
    return "0.00% packet loss" in text or "0% packet loss" in text


def _parse_vrrp_states(output: str) -> dict[str, str]:
    states: dict[str, str] = {}
    for line in output.splitlines():
        match = re.search(r"\b(10|20|30|40)\b.*\b(Master|Backup|Initialize)\b", line, re.I)
        if match:
            states[match.group(1)] = match.group(2).capitalize()
    return states


def _vrrp_check(name: str, output: str) -> dict[str, Any]:
    expected = {
        "LSW1": {"10": "Master", "20": "Backup", "30": "Master", "40": "Backup"},
        "LSW4": {"10": "Backup", "20": "Master", "30": "Backup", "40": "Master"},
    }[name]
    actual = _parse_vrrp_states(output)
    missing_or_wrong = {
        vlan: {"expected": state, "actual": actual.get(vlan)}
        for vlan, state in expected.items()
        if actual.get(vlan) != state
    }
    return {
        "pass": not missing_or_wrong,
        "expected": expected,
        "actual": actual,
        "failures": missing_or_wrong,
    }


def _parse_stp_instance_rows(output: str, instance: str) -> list[str]:
    rows = []
    for line in output.splitlines():
        fields = line.split()
        if fields and fields[0] == instance:
            rows.append(line)
    return rows


def _mstp_check(name: str, output: str) -> dict[str, Any]:
    expected_root_instance = "1" if name == "LSW1" else "2"
    rows = _parse_stp_instance_rows(output, expected_root_instance)
    has_root_port = any(re.search(r"\bROOT\b", row, re.I) for row in rows)
    has_forwarding_port = any(re.search(r"\bFORWARDING\b", row, re.I) for row in rows)
    return {
        "pass": bool(rows) and not has_root_port and has_forwarding_port,
        "expected_root_instance": expected_root_instance,
        "instance_rows": rows,
        "reason": None if rows else "未找到对应 MSTP 实例行",
    }


def _parse_pool_used(output: str) -> int | None:
    match = re.search(r"\bUsed\s*[:=]\s*(\d+)\b", output, re.I)
    if match:
        return int(match.group(1))

    table_match = re.search(
        r"\bTotal\s+Used\s+Idle\b.*?\n\s*\S+.*?\b(\d+)\s+(\d+)\s+(\d+)\b",
        output,
        re.I | re.S,
    )
    if table_match:
        return int(table_match.group(2))
    return None


def _dhcp_check(checks: dict[str, Any]) -> dict[str, Any]:
    by_vlan: dict[str, dict[str, Any]] = {}
    for vlan in ("10", "20", "30", "40"):
        pool = f"VLAN{vlan}"
        lsw1_used = _parse_pool_used(checks["LSW1"]["dhcp_pools"][pool])
        lsw4_used = _parse_pool_used(checks["LSW4"]["dhcp_pools"][pool])
        total_used = (lsw1_used or 0) + (lsw4_used or 0)
        by_vlan[pool] = {
            "pass": total_used > 0,
            "total_used": total_used,
            "LSW1_used": lsw1_used,
            "LSW4_used": lsw4_used,
        }
    return {
        "pass": all(item["pass"] for item in by_vlan.values()),
        "pools": by_vlan,
    }


def _nat_check(output: str) -> dict[str, Any]:
    text = output.lower()
    has_acl = "2000" in text
    has_easyip = "easyip" in text or "easy-ip" in text
    has_interface = "gigabitethernet0/0/0" in text
    return {
        "pass": has_acl and has_easyip and has_interface,
        "acl_2000": has_acl,
        "easyip": has_easyip,
        "internet_interface": has_interface,
    }


def verify_campus_lab() -> dict[str, Any]:
    devices, _links = _load_current_topology()
    runtime = _runtime_devices(devices)
    checks: dict[str, Any] = {}
    for name in ["LSW1", "LSW4"]:
        port = runtime[name].port
        checks[name] = {
            "vrrp": _run_command(port, "display vrrp brief", timeout=8),
            "stp": _run_command(port, "display stp brief", timeout=8),
            "default_route": _run_command(port, "display ip routing-table 0.0.0.0", timeout=8),
            "ping_internet": _run_command(port, "ping -c 5 120.36.2.2", timeout=18),
            "dhcp_pools": {
                f"VLAN{vlan}": _run_command(port, f"display ip pool name VLAN{vlan}", timeout=8)
                for vlan in ("10", "20", "30", "40")
            },
        }
    checks["AR2"] = {
        "nat": _run_command(runtime["AR2"].port, "display nat outbound", timeout=8),
        "route": _run_command(runtime["AR2"].port, "display ip routing-table", timeout=8),
    }
    structured_checks = {
        "ping": {
            "LSW1": _ping_ok(checks["LSW1"]["ping_internet"]),
            "LSW4": _ping_ok(checks["LSW4"]["ping_internet"]),
        },
        "vrrp": {
            "LSW1": _vrrp_check("LSW1", checks["LSW1"]["vrrp"]),
            "LSW4": _vrrp_check("LSW4", checks["LSW4"]["vrrp"]),
        },
        "mstp": {
            "LSW1": _mstp_check("LSW1", checks["LSW1"]["stp"]),
            "LSW4": _mstp_check("LSW4", checks["LSW4"]["stp"]),
        },
        "dhcp": _dhcp_check(checks),
        "nat": _nat_check(checks["AR2"]["nat"]),
    }
    success = (
        all(structured_checks["ping"].values())
        and all(item["pass"] for item in structured_checks["vrrp"].values())
        and all(item["pass"] for item in structured_checks["mstp"].values())
        and structured_checks["dhcp"]["pass"]
        and structured_checks["nat"]["pass"]
    )
    return {
        "success": success,
        "topology": str(get_topology_path()),
        "summary": {
            "ping_120_36_2_2": structured_checks["ping"],
            "vrrp": {
                name: item["pass"]
                for name, item in structured_checks["vrrp"].items()
            },
            "mstp": {
                name: item["pass"]
                for name, item in structured_checks["mstp"].items()
            },
            "dhcp": structured_checks["dhcp"]["pass"],
            "nat": structured_checks["nat"]["pass"],
        },
        "structured_checks": structured_checks,
        "checks": checks,
    }


def save_campus_lab() -> dict[str, Any]:
    devices, _links = _load_current_topology()
    runtime = _runtime_devices(devices)
    results = {
        name: _save_device(runtime[name])
        for name in ["internet", "AR2", "LSW1", "LSW2", "LSW3", "LSW4"]
    }
    return {
        "success": all(result["success"] for result in results.values()),
        "topology": str(get_topology_path()),
        "results": results,
    }


def execute_campus_lab(
    confirmed: bool = False,
    mode: str = "apply_and_verify",
    save_on_success: bool = True,
) -> dict[str, Any]:
    if mode not in {"plan", "apply", "apply_and_verify", "verify"}:
        return {"success": False, "error": f"unsupported mode: {mode}"}
    plan = plan_campus_lab()
    if mode == "plan" or not plan.get("success"):
        return plan
    if mode == "verify":
        verification = verify_campus_lab()
        save_result = None
        overall = verification.get("success", False)
        if save_on_success and overall:
            save_result = save_campus_lab()
            overall = save_result.get("success", False)
        if save_result is None:
            return verification
        return {
            **verification,
            "success": overall,
            "save": save_result,
        }
    if not confirmed:
        return {"success": False, "error": "write operations require confirmed=true", "plan": plan}
    apply_result = apply_campus_lab()
    verification = verify_campus_lab() if mode == "apply_and_verify" else None
    overall = apply_result.get("success", False) and (
        verification is None or verification.get("success", False)
    )
    save_result = None
    if save_on_success and overall:
        save_result = save_campus_lab()
        overall = save_result.get("success", False)
    return {
        "success": overall,
        "topology": _safe_topology_value(),
        "plan": plan,
        "apply": apply_result,
        "verification": verification,
        "save": save_result,
    }
