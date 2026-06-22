"""Offline reference-config analysis for enterprise eNSP labs.

This service reads sibling configuration samples near the active topology and
extracts reusable patterns plus structured protocol templates and candidate
reference drafts for:
- IPSec/GRE VPN interconnection
- Router-based DHCP and relay design
- WiFi SSID/VLAN/AP grouping
- Guest isolation ACLs
- Selective internet access via NAT/ACL
"""

from __future__ import annotations

import re
import os
from pathlib import Path
from typing import Any

from backend.topology.config import get_topology_path
from backend.topology.parser import parse_topology


_CFG_DIR_CANDIDATES = ("配置", "config-samples", "configs")


def _read_text(path: Path) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gb18030", "gbk", "utf-16"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeError:
            continue
    return path.read_text(encoding="utf-8", errors="ignore")


def _config_dir_for_workspace(workspace_dir: Path) -> Path | None:
    for name in _CFG_DIR_CANDIDATES:
        candidate = workspace_dir / name
        if candidate.exists() and candidate.is_dir():
            return candidate
    return None


def _topology_from_workspace_dir(workspace_dir: Path) -> Path:
    named_topo = workspace_dir / f"{workspace_dir.name}.topo"
    if named_topo.exists():
        return named_topo.resolve()

    topo_files = sorted(workspace_dir.glob("*.topo"))
    if len(topo_files) == 1:
        return topo_files[0].resolve()
    if len(topo_files) > 1:
        names = ", ".join(path.name for path in topo_files)
        raise RuntimeError(
            f"工作目录存在多个 .topo 文件，请设置 TOPOLOGY_FILE 明确指定: {workspace_dir}: {names}"
        )
    raise FileNotFoundError(f"工作目录中未找到 .topo 文件: {workspace_dir}")


def _resolve_reference_topology_path() -> Path:
    try:
        return get_topology_path().resolve()
    except (FileNotFoundError, RuntimeError):
        workspace_env = os.getenv("ENSP_MCP_WORKSPACE_DIR")
        if not workspace_env:
            raise
        return _topology_from_workspace_dir(Path(workspace_env).expanduser().resolve())


def _load_cfg_texts(config_dir: Path) -> dict[str, str]:
    return {path.stem: _read_text(path) for path in sorted(config_dir.glob("*.cfg"))}


def _split_sections(text: str) -> list[str]:
    return [section.strip() for section in re.split(r"^\s*#\s*$", text, flags=re.M) if section.strip()]


def _commands_from_section(section: str) -> list[str]:
    return [line.rstrip() for line in section.splitlines() if line.strip()]


def _dedupe(commands: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for command in commands:
        normalized = command.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def _sections_matching(text: str, *keywords: str) -> list[str]:
    sections = _split_sections(text)
    matches: list[str] = []
    for section in sections:
        if all(keyword in section for keyword in keywords):
            matches.append(section)
    return matches


def _extract_ipsec_summary(cfg_texts: dict[str, str]) -> dict[str, Any]:
    firewalls: dict[str, Any] = {}
    peers: list[dict[str, Any]] = []

    for name, text in cfg_texts.items():
        lowered = text.lower()
        if "ipsec policy" not in lowered and "tunnel-protocol gre" not in lowered:
            continue

        remote_matches = re.findall(r"remote-address\s+([0-9.]+)", text, re.I)
        tunnel_sources = re.findall(r"^\s*source\s+([0-9.]+)\s*$", text, re.I | re.M)
        tunnel_dests = re.findall(r"^\s*destination\s+([0-9.]+)\s*$", text, re.I | re.M)
        ipsec_policies = re.findall(r"ipsec policy\s+(\S+)", text, re.I)
        ike_peers = re.findall(r"ike peer\s+(\S+)", text, re.I)
        acls = re.findall(r"acl number\s+(\d+)", text, re.I)

        firewalls[name] = {
            "remote_addresses": sorted(set(remote_matches)),
            "tunnel_sources": sorted(set(tunnel_sources)),
            "tunnel_destinations": sorted(set(tunnel_dests)),
            "ipsec_policies": sorted(set(ipsec_policies)),
            "ike_peers": sorted(set(ike_peers)),
            "acl_numbers": sorted(set(acls)),
            "has_ipsec": "ipsec policy" in lowered,
            "has_gre": "tunnel-protocol gre" in lowered,
        }

    if "Z-FW-1" in firewalls and "F-FW-1" in firewalls:
        peers.append({"from": "Z-FW-1", "to": "F-FW-1", "remote_addresses": firewalls["Z-FW-1"]["remote_addresses"], "tunnel_destinations": firewalls["Z-FW-1"]["tunnel_destinations"]})
        peers.append({"from": "F-FW-1", "to": "Z-FW-1", "remote_addresses": firewalls["F-FW-1"]["remote_addresses"], "tunnel_destinations": firewalls["F-FW-1"]["tunnel_destinations"]})

    return {
        "detected": bool(firewalls),
        "devices": firewalls,
        "peerings": peers,
        "summary": "总部与分部通过防火墙上的 IPSec + GRE 互联" if peers else "检测到 IPSec/GRE 参考配置",
    }


def _extract_router_dhcp_summary(cfg_texts: dict[str, str]) -> dict[str, Any]:
    routers: dict[str, Any] = {}
    for name, text in cfg_texts.items():
        lowered = text.lower()
        if "ip pool" not in lowered and "dhcp relay server-ip" not in lowered:
            continue

        pools: list[dict[str, Any]] = []
        for match in re.finditer(
            r"ip pool\s+(\S+)\s+gateway-list\s+([0-9.]+)\s+network\s+([0-9.]+)\s+mask\s+([0-9.]+)",
            text,
            re.I,
        ):
            pools.append({"pool": match.group(1), "gateway": match.group(2), "network": match.group(3), "mask": match.group(4)})
        relays = re.findall(r"dhcp relay server-ip\s+([0-9.]+)", text, re.I)
        routers[name] = {
            "pool_count": len(pools),
            "pools": pools,
            "relay_servers": sorted(set(relays)),
            "acts_as_pool_server": bool(pools),
            "acts_as_relay": bool(relays),
        }

    return {
        "detected": bool(routers),
        "devices": routers,
        "summary": "既有三层交换机 DHCP，也有分部路由器 DHCP/Relay 参考配置" if routers else "未检测到路由器 DHCP 参考配置",
    }


def _extract_wifi_summary(cfg_texts: dict[str, str]) -> dict[str, Any]:
    text = cfg_texts.get("Z-WIFI-AC1", "")
    if not text:
        return {"detected": False, "summary": "未检测到 AC 参考配置"}

    ssids = re.findall(r"ssid\s+([A-Za-z0-9_-]+)", text)
    service_vlans = re.findall(r"service-vlan vlan-id\s+(\d+)", text, re.I)
    ap_groups = re.findall(r"ap-group name\s+(\S+)", text, re.I)
    ap_ids = re.findall(r"ap-id\s+(\d+).*?ap-mac\s+([0-9a-f-]+)", text, re.I)

    guest_vlan = None
    enterprise_vlan = None
    guest_block = re.search(r"vap-profile name\s+vap_guest(.*?)vap-profile name\s+vap_enterprise", text, re.I | re.S)
    if guest_block:
        match = re.search(r"service-vlan vlan-id\s+(\d+)", guest_block.group(1), re.I)
        if match:
            guest_vlan = match.group(1)
    enterprise_block = re.search(r"vap-profile name\s+vap_enterprise(.*?)(?:wds-profile name|$)", text, re.I | re.S)
    if enterprise_block:
        match = re.search(r"service-vlan vlan-id\s+(\d+)", enterprise_block.group(1), re.I)
        if match:
            enterprise_vlan = match.group(1)

    return {
        "detected": True,
        "ssid_names": sorted(set(ssids)),
        "service_vlans": sorted(set(service_vlans)),
        "guest_vlan": guest_vlan,
        "enterprise_vlan": enterprise_vlan,
        "ap_groups": sorted(set(ap_groups)),
        "ap_count": len(ap_ids),
        "summary": "AC 参考配置包含企业与访客双 SSID，并通过业务 VLAN 区分无线流量",
    }


def _extract_access_control_summary(cfg_texts: dict[str, str]) -> dict[str, Any]:
    acl_summaries: dict[str, Any] = {}
    for name in ("Z-Core-SW1", "Z-Core-SW2", "Z-DataCenter-SW1", "Z-FW-1", "F-FW-1"):
        text = cfg_texts.get(name)
        if not text:
            continue
        acl_numbers = re.findall(r"acl number\s+(\d+)", text, re.I)
        deny_rules = re.findall(r"rule\s+\d+\s+deny\s+ip\s+source\s+([0-9.]+)\s+[0-9.]+\s+destination\s+([0-9.]+)", text, re.I)
        nat_sources = re.findall(r"source-address\s+([0-9.]+)\s+mask\s+([0-9.]+)", text, re.I)
        traffic_filters = re.findall(r"traffic-filter\s+inbound\s+acl\s+(\d+)", text, re.I)
        acl_summaries[name] = {
            "acl_numbers": sorted(set(acl_numbers)),
            "traffic_filters": sorted(set(traffic_filters)),
            "deny_pairs": [{"source": source, "destination": destination} for source, destination in deny_rules],
            "nat_sources": [{"network": source, "mask": mask} for source, mask in nat_sources],
        }

    guest_pairs = []
    for name in ("Z-Core-SW1", "Z-Core-SW2", "Z-DataCenter-SW1"):
        item = acl_summaries.get(name)
        if not item:
            continue
        for pair in item["deny_pairs"]:
            if pair["source"] == "10.10.101.0" or pair["source"].startswith("10.10.101"):
                guest_pairs.append({"device": name, **pair})

    return {
        "detected": bool(acl_summaries),
        "devices": acl_summaries,
        "guest_isolation_rules": guest_pairs,
        "summary": "访客网与内网隔离、以及公网访问控制主要通过 ACL / traffic-filter / NAT policy 实现",
    }


def _extract_public_access_summary(cfg_texts: dict[str, str]) -> dict[str, Any]:
    fw_text = cfg_texts.get("Z-FW-1", "")
    core_text = cfg_texts.get("Z-Core-SW1", "") + "\n" + cfg_texts.get("Z-Core-SW2", "")
    if not fw_text:
        return {"detected": False, "summary": "未检测到总部公网访问控制参考配置"}

    nat_networks = sorted(set(re.findall(r"source-address\s+([0-9.]+)\s+mask\s+255\.255\.255\.0", fw_text, re.I)))
    vlan_networks = sorted(set(re.findall(r"ip address\s+(10\.10\.\d+\.\d+)\s+255\.255\.255\.0", core_text, re.I)))
    normalized_vlan_networks = sorted({re.sub(r"\.\d+$", ".0", network) for network in vlan_networks if not network.startswith("10.10.99.") and not network.startswith("10.10.200.")})
    blocked = [network for network in normalized_vlan_networks if network not in nat_networks]

    return {
        "detected": True,
        "nat_enabled_subnets": nat_networks,
        "candidate_user_subnets": normalized_vlan_networks,
        "likely_public_blocked_subnets": blocked,
        "summary": "总部公网访问采用选择性源 NAT，未进入 NAT 策略的业务 VLAN 默认不能访问公网",
    }


def _build_ipsec_template(pattern: dict[str, Any]) -> dict[str, Any]:
    devices = pattern.get("devices", {})
    required_acl_numbers = sorted({acl for item in devices.values() for acl in item.get("acl_numbers", [])})
    required_policies = sorted({policy for item in devices.values() for policy in item.get("ipsec_policies", [])})
    required_ike_peers = sorted({peer for item in devices.values() for peer in item.get("ike_peers", [])})
    return {
        "template_type": "site_to_site_ipsec_gre",
        "applicable": bool(pattern.get("detected")),
        "roles": ["hq_firewall", "branch_firewall"],
        "peer_examples": pattern.get("peerings", []),
        "required_objects": {"acl_numbers": required_acl_numbers, "ike_peers": required_ike_peers, "ipsec_policies": required_policies},
        "device_examples": devices,
        "workflow": ["定义感兴趣流 ACL", "创建 IKE peer 与对端地址", "创建 IPSec policy 并绑定 ACL", "创建 GRE Tunnel 并指向公网对端", "在 Tunnel 上承载总部与分部互访路由"],
    }


def _build_dhcp_template(pattern: dict[str, Any]) -> dict[str, Any]:
    pools = []
    relays = []
    for device_name, item in pattern.get("devices", {}).items():
        pools.extend({"device": device_name, **pool} for pool in item.get("pools", []))
        if item.get("relay_servers"):
            relays.append({"device": device_name, "relay_servers": item.get("relay_servers", [])})
    return {
        "template_type": "dhcp_pool_and_relay",
        "applicable": bool(pattern.get("detected")),
        "pool_examples": pools,
        "relay_examples": relays,
        "workflow": ["在网关设备或专用路由器上定义地址池", "为每个业务网段设置 gateway-list 与 network/mask", "在非池服务器的三层接口上启用 DHCP relay 并指向 server-ip", "根据 VLAN 网关角色决定使用本地池还是 Relay"],
    }


def _build_wifi_template(wifi: dict[str, Any], access: dict[str, Any]) -> dict[str, Any]:
    ssid_profiles = []
    for ssid in wifi.get("ssid_names", []):
        lowered = ssid.lower()
        role = "guest" if "guest" in lowered else "enterprise" if "enterprise" in lowered else "generic"
        service_vlan = wifi.get("guest_vlan") if role == "guest" else wifi.get("enterprise_vlan") if role == "enterprise" else None
        ssid_profiles.append({"ssid": ssid, "role": role, "service_vlan": service_vlan})
    return {
        "template_type": "ac_ssid_vlan_isolation",
        "applicable": bool(wifi.get("detected")),
        "ssid_profiles": ssid_profiles,
        "ap_groups": wifi.get("ap_groups", []),
        "ap_count": wifi.get("ap_count", 0),
        "guest_isolation_required": bool(access.get("guest_isolation_rules")),
        "guest_isolation_examples": access.get("guest_isolation_rules", []),
        "workflow": ["在 AC 上创建企业与访客 SSID/VAP", "为不同 SSID 绑定不同业务 VLAN", "将 VAP 下发到 AP Group", "在核心或汇聚侧通过 ACL 阻断访客 VLAN 访问内网"],
    }


def _build_access_template(pattern: dict[str, Any]) -> dict[str, Any]:
    guest_sources = sorted({pair["source"] for pair in pattern.get("guest_isolation_rules", [])})
    protected_destinations = sorted({pair["destination"] for pair in pattern.get("guest_isolation_rules", [])})
    return {
        "template_type": "guest_acl_isolation",
        "applicable": bool(pattern.get("detected")),
        "guest_sources": guest_sources,
        "protected_destinations": protected_destinations,
        "rule_examples": pattern.get("guest_isolation_rules", []),
        "workflow": ["识别访客源网段", "在核心/数据中心边界定义 deny ip source guest destination intranet 规则", "通过 traffic-filter 绑定到入方向接口或 VLANIF"],
    }


def _build_public_access_template(pattern: dict[str, Any]) -> dict[str, Any]:
    return {
        "template_type": "selective_source_nat",
        "applicable": bool(pattern.get("detected")),
        "nat_enabled_subnets": pattern.get("nat_enabled_subnets", []),
        "blocked_subnets": pattern.get("likely_public_blocked_subnets", []),
        "candidate_user_subnets": pattern.get("candidate_user_subnets", []),
        "workflow": ["在出口防火墙或路由器上通过源地址范围定义 NAT 放行名单", "需要允许上网的业务 VLAN 进入 NAT 策略", "未进入 NAT 或 ACL 放行名单的 VLAN 默认不能访问公网"],
    }


def _build_templates(patterns: dict[str, Any]) -> dict[str, Any]:
    return {
        "ipsec_vpn": _build_ipsec_template(patterns.get("ipsec_vpn", {})),
        "router_dhcp": _build_dhcp_template(patterns.get("router_dhcp", {})),
        "wifi": _build_wifi_template(patterns.get("wifi", {}), patterns.get("access_control", {})),
        "access_control": _build_access_template(patterns.get("access_control", {})),
        "public_access": _build_public_access_template(patterns.get("public_access", {})),
    }


def _draft(title: str, purpose: str, devices: list[dict[str, Any]], warnings: list[str]) -> dict[str, Any]:
    return {
        "draft_id": f"reference-{title}",
        "purpose": purpose,
        "reference_only": True,
        "requires_confirmation": False,
        "devices": devices,
        "warnings": warnings,
    }


def _build_ipsec_reference_draft(cfg_texts: dict[str, str]) -> dict[str, Any]:
    devices = []
    for device_name in ("Z-FW-1", "F-FW-1"):
        text = cfg_texts.get(device_name, "")
        if not text:
            continue
        commands: list[str] = []
        for section in _sections_matching(text, "acl number 3000"):
            commands.extend(_commands_from_section(section))
        for keyword in ("ipsec proposal", "ike proposal 5", "ike peer ", "ipsec policy "):
            for section in _split_sections(text):
                if keyword in section:
                    commands.extend(_commands_from_section(section))
        for section in _split_sections(text):
            if "interface Tunnel0" in section or ("interface GigabitEthernet1/0/0" in section and "ipsec policy" in section):
                commands.extend(_commands_from_section(section))
        route_lines = [line.strip() for line in text.splitlines() if line.strip().startswith("ip route-static") and ("172.16.0.0" in line or "10.10.0.0" in line)]
        commands.extend(route_lines)
        devices.append({"device_name": device_name, "commands": _dedupe(commands), "purpose": "总部/分部 IPSec + GRE 参考命令块"})
    return _draft("ipsec_vpn", "总部与分部站点互联参考草案", devices, ["该草案来源于样例配置，适合做协议做法参考，不建议直接原样下发。"])


def _build_dhcp_reference_draft(cfg_texts: dict[str, str]) -> dict[str, Any]:
    devices = []
    for device_name in ("Z-Core-SW1", "F-DHCP-Sercver", "F-Core-SW1"):
        text = cfg_texts.get(device_name, "")
        if not text:
            continue
        commands: list[str] = []
        for section in _split_sections(text):
            if section.startswith("ip pool") or " dhcp relay server-ip " in f" {section} " or "dhcp relay server-ip" in section:
                commands.extend(_commands_from_section(section))
            elif section.startswith("interface Vlanif") and ("dhcp select global" in section or "dhcp select relay" in section):
                commands.extend(_commands_from_section(section))
        devices.append({"device_name": device_name, "commands": _dedupe(commands), "purpose": "DHCP 池/Relay 参考命令块"})
    return _draft("router_dhcp", "DHCP 与 Relay 参考草案", devices, ["该草案保留了样例中的地址池与 Relay 思路，使用前需按当前网段核对。"])


def _build_wifi_reference_draft(cfg_texts: dict[str, str]) -> dict[str, Any]:
    text = cfg_texts.get("Z-WIFI-AC1", "")
    commands: list[str] = []
    if text:
        for section in _split_sections(text):
            if section.startswith("interface Vlanif99") or section.startswith("interface Vlanif100") or section.startswith("interface Vlanif101"):
                commands.extend(_commands_from_section(section))
            elif "capwap source interface vlanif99" in section:
                commands.extend(_commands_from_section(section))
            elif section.startswith("wlan"):
                commands.extend(_commands_from_section(section))
    return _draft("wifi", "无线下发与访客/企业 SSID 参考草案", [{"device_name": "Z-WIFI-AC1", "commands": _dedupe(commands), "purpose": "AC 无线业务与 AP 组下发参考命令块"}], ["该草案展示了 AC、SSID、VAP、AP Group 的组合方式，使用前需核对 AP 实际接入关系。"])


def _build_access_reference_draft(cfg_texts: dict[str, str]) -> dict[str, Any]:
    devices = []
    for device_name, acl_id in (("Z-Core-SW1", "3050"), ("Z-Core-SW2", "3050"), ("Z-DataCenter-SW1", "3000")):
        text = cfg_texts.get(device_name, "")
        if not text:
            continue
        commands: list[str] = []
        for section in _split_sections(text):
            if f"acl number {acl_id}" in section or "traffic-filter inbound acl" in section:
                commands.extend(_commands_from_section(section))
        devices.append({"device_name": device_name, "commands": _dedupe(commands), "purpose": "访客隔离 ACL 参考命令块"})
    return _draft("access_control", "访客网与内网隔离参考草案", devices, ["该草案体现的是 ACL 与 traffic-filter 绑定思路，实际部署时需结合 VLANIF 入方向。"])


def _build_public_access_reference_draft(cfg_texts: dict[str, str]) -> dict[str, Any]:
    text = cfg_texts.get("Z-FW-1", "")
    commands: list[str] = []
    if text:
        for section in _split_sections(text):
            if "nat-policy" in section:
                commands.extend(_commands_from_section(section))
    return _draft("public_access", "选择性公网访问控制参考草案", [{"device_name": "Z-FW-1", "commands": _dedupe(commands), "purpose": "出口 NAT 白名单与 no-nat 参考命令块"}], ["该草案展示的是允许上网网段进入 NAT、其他业务 VLAN 默认不出公网的做法。"])


def _build_reference_drafts(cfg_texts: dict[str, str]) -> dict[str, Any]:
    return {
        "ipsec_vpn": _build_ipsec_reference_draft(cfg_texts),
        "router_dhcp": _build_dhcp_reference_draft(cfg_texts),
        "wifi": _build_wifi_reference_draft(cfg_texts),
        "access_control": _build_access_reference_draft(cfg_texts),
        "public_access": _build_public_access_reference_draft(cfg_texts),
    }



def _build_capability_catalog(patterns: dict[str, Any], templates: dict[str, Any]) -> dict[str, Any]:
    return {
        "ipsec_vpn": {
            "available": bool(patterns.get("ipsec_vpn", {}).get("detected")),
            "capability": "具备基于 IKE + IPSec Policy + GRE Tunnel 的站点到站点互联做法认知",
            "required_parameters": ["本端公网地址", "对端公网地址", "感兴趣流 ACL", "IKE peer 名称", "IPSec policy 名称", "Tunnel 地址/路由"],
            "validation_focus": ["IKE peer/remote-address", "ipsec policy 绑定 ACL", "Tunnel source/destination", "互访静态路由或等价路由"],
            "template_type": templates.get("ipsec_vpn", {}).get("template_type"),
        },
        "router_dhcp": {
            "available": bool(patterns.get("router_dhcp", {}).get("detected")),
            "capability": "具备路由器/三层交换机本地地址池与 DHCP Relay 的组合做法认知",
            "required_parameters": ["地址池网段", "网关地址", "DNS", "Relay Server IP", "承载 VLANIF/三层接口"],
            "validation_focus": ["ip pool network/mask", "gateway-list", "dhcp select global/relay", "dhcp relay server-ip"],
            "template_type": templates.get("router_dhcp", {}).get("template_type"),
        },
        "wifi": {
            "available": bool(patterns.get("wifi", {}).get("detected")),
            "capability": "具备 AC/SSID/VAP/AP Group 的无线下发做法认知，并能区分企业与访客无线",
            "required_parameters": ["SSID 名称", "service-vlan", "安全配置", "AP Group", "CAPWAP 管理 VLAN"],
            "validation_focus": ["ssid-profile", "vap-profile -> service-vlan", "ap-group 绑定", "capwap source interface"],
            "template_type": templates.get("wifi", {}).get("template_type"),
        },
        "access_control": {
            "available": bool(patterns.get("access_control", {}).get("detected")),
            "capability": "具备通过 ACL + traffic-filter 实现访客网与内网隔离的做法认知",
            "required_parameters": ["访客源网段", "受保护目标网段", "ACL 编号", "绑定方向/接口"],
            "validation_focus": ["deny ip source guest destination intranet", "traffic-filter inbound acl"],
            "template_type": templates.get("access_control", {}).get("template_type"),
        },
        "public_access": {
            "available": bool(patterns.get("public_access", {}).get("detected")),
            "capability": "具备通过 NAT 白名单/No-NAT 规则限制特定 VLAN 访问公网的做法认知",
            "required_parameters": ["允许公网的源网段集合", "禁止公网的源网段集合", "No-NAT 目的网段", "出口接口或 zone"],
            "validation_focus": ["nat-policy", "source-address 放行名单", "action no-nat", "未进入 NAT 的 VLAN 不出公网"],
            "template_type": templates.get("public_access", {}).get("template_type"),
        },
    }
def analyze_reference_configs() -> dict[str, Any]:
    topo_path = _resolve_reference_topology_path()
    workspace_dir = topo_path.parent
    topo = parse_topology(topo_path)
    config_dir = _config_dir_for_workspace(workspace_dir)

    if config_dir is None:
        return {"success": False, "topology": str(topo_path), "workspace_dir": str(workspace_dir), "error": "当前拓扑目录旁未找到参考配置目录（如 配置/）"}

    cfg_texts = _load_cfg_texts(config_dir)
    if not cfg_texts:
        return {"success": False, "topology": str(topo_path), "workspace_dir": str(workspace_dir), "config_dir": str(config_dir), "error": "参考配置目录中没有 .cfg 文件"}

    topology_device_names = sorted(device.name for device in topo.devices)
    matched_config_devices = sorted(name for name in cfg_texts if name in topology_device_names)
    unmatched_config_devices = sorted(name for name in cfg_texts if name not in topology_device_names)

    patterns = {
        "ipsec_vpn": _extract_ipsec_summary(cfg_texts),
        "router_dhcp": _extract_router_dhcp_summary(cfg_texts),
        "wifi": _extract_wifi_summary(cfg_texts),
        "access_control": _extract_access_control_summary(cfg_texts),
        "public_access": _extract_public_access_summary(cfg_texts),
    }
    templates = _build_templates(patterns)
    reference_drafts = _build_reference_drafts(cfg_texts)
    capability_catalog = _build_capability_catalog(patterns, templates)
    knowledge_points = [
        "IPSec/GRE 站点互联参考",
        "路由器/三层交换机 DHCP 与 Relay 参考",
        "无线 SSID、VLAN、AP 组下发参考",
        "访客隔离 ACL 参考",
        "选择性公网访问控制参考",
    ]

    return {
        "success": True,
        "topology": str(topo_path),
        "workspace_dir": str(workspace_dir),
        "config_dir": str(config_dir),
        "topology_device_count": len(topo.devices),
        "config_file_count": len(cfg_texts),
        "matched_config_devices": matched_config_devices,
        "unmatched_config_devices": unmatched_config_devices,
        "knowledge_points": knowledge_points,
        "patterns": patterns,
        "templates": templates,
        "reference_drafts": reference_drafts,
        "capability_catalog": capability_catalog,
        "template_summary": {
            name: template.get("template_type")
            for name, template in templates.items()
            if template.get("applicable")
        },
    }



