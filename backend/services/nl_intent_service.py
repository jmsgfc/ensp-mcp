"""Natural-language planning service with reference-config awareness.

This module keeps the original rule-based planner, but augments its results
with learned protocol patterns, templates, reference drafts, and a capability
catalog. It stays at the capability layer rather than mapping to a specific
live topology rollout.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol

from backend.adapters.base_adapter import BaseAdapter, DeviceDiagnostics
from backend.services.reference_config_service import analyze_reference_configs
from backend.topology.config import get_topology_path
from backend.topology.parser import parse_topology
from backend.topology.validator import load_devices_yaml


@dataclass
class IntentResult:
    user_request: str
    intent_type: str
    confidence: float
    supported: bool
    summary: str
    target_devices: list[str] = field(default_factory=list)
    reason: str = ""


@dataclass
class NlPlanResponse:
    user_request: str
    intent_type: str
    supported: bool
    summary: str
    target_devices: list[str]
    draft_type: str
    confidence: float = 0.0
    draft: Optional[dict[str, Any]] = None
    warnings: list[str] = field(default_factory=list)
    next_action: str = ""
    reason: str = ""
    error_message: str = ""
    reference_capabilities: list[str] = field(default_factory=list)
    matched_reference_patterns: list[str] = field(default_factory=list)
    reference_details: dict[str, Any] = field(default_factory=dict)
    reference_templates: dict[str, Any] = field(default_factory=dict)
    reference_drafts: dict[str, Any] = field(default_factory=dict)
    protocol_capabilities: dict[str, Any] = field(default_factory=dict)


class NlParser(Protocol):
    def parse(self, user_request: str) -> IntentResult:
        ...


_INTENT_RULES: dict[str, dict[str, Any]] = {
    "pc_connectivity": {
        "keywords": ["pc1", "pc2", "互通", "连通", "ping", "静态路由"],
        "summary_tpl": "为 {devices} 规划互通能力",
        "draft_type": "static_route",
    },
    "ospf": {
        "keywords": ["ospf", "动态路由", "路由协议"],
        "summary_tpl": "为 {devices} 规划 OSPF 路由协议",
        "draft_type": "ospf",
    },
    "vlan": {
        "keywords": ["vlan", "交换机", "二层", "trunk", "access"],
        "summary_tpl": "为交换网络规划 VLAN 与二层转发配置",
        "draft_type": "vlan",
    },
    "dhcp": {
        "keywords": ["dhcp", "自动获取", "地址分配", "地址池", "relay"],
        "summary_tpl": "规划 DHCP 地址分配与 Relay 方案",
        "draft_type": "dhcp",
    },
    "ipsec_vpn": {
        "keywords": ["ipsec", "ipsecvpn", "vpn", "gre", "总部", "分部", "隧道"],
        "summary_tpl": "总结当前实验的 IPSec/GRE 站点互联做法",
        "draft_type": "reference",
    },
    "wifi": {
        "keywords": ["wifi", "ssid", "无线", "ac", "ap", "访客wifi", "企业wifi"],
        "summary_tpl": "总结当前实验的无线下发与 SSID/VLAN 设计做法",
        "draft_type": "reference",
    },
    "access_control": {
        "keywords": ["acl", "访问控制", "隔离", "访客", "traffic-filter", "内网"],
        "summary_tpl": "总结当前实验的 ACL/隔离控制做法",
        "draft_type": "reference",
    },
    "public_access": {
        "keywords": ["公网", "nat", "上网", "禁止上网", "不能访问公网", "访问公网"],
        "summary_tpl": "总结当前实验的选择性公网访问控制做法",
        "draft_type": "reference",
    },
}

_REFERENCE_PATTERN_MAP = {
    "dhcp": ["router_dhcp"],
    "ipsec_vpn": ["ipsec_vpn"],
    "wifi": ["wifi", "access_control"],
    "access_control": ["access_control"],
    "public_access": ["public_access", "access_control"],
}
_REFERENCE_TEMPLATE_MAP = {
    "dhcp": ["router_dhcp"],
    "ipsec_vpn": ["ipsec_vpn"],
    "wifi": ["wifi", "access_control"],
    "access_control": ["access_control"],
    "public_access": ["public_access"],
}
_REFERENCE_DRAFT_MAP = {
    "dhcp": ["router_dhcp"],
    "ipsec_vpn": ["ipsec_vpn"],
    "wifi": ["wifi", "access_control"],
    "access_control": ["access_control"],
    "public_access": ["public_access"],
}
_INTENT_PRIORITY = {
    "wifi": 80,
    "ipsec_vpn": 70,
    "public_access": 60,
    "access_control": 50,
    "dhcp": 40,
    "vlan": 30,
    "ospf": 20,
    "pc_connectivity": 10,
}


class RuleBasedParser:
    def parse(self, user_request: str) -> IntentResult:
        text = user_request.lower().strip()
        if not text:
            return IntentResult(
                user_request=user_request,
                intent_type="unknown",
                confidence=0.0,
                supported=False,
                summary="",
                reason="输入为空",
            )

        device_names = _load_device_names()
        target_devices = [name for name in device_names if name.lower() in text]

        scores: dict[str, float] = {}
        matched_keywords: dict[str, list[str]] = {}
        for intent_type, rule in _INTENT_RULES.items():
            hits = [keyword for keyword in rule["keywords"] if keyword in text]
            if not hits:
                continue
            raw_score = len(hits) / len(rule["keywords"])
            scores[intent_type] = max(0.5, min(1.0, raw_score + 0.3))
            matched_keywords[intent_type] = hits

        wifi_markers = ["wifi", "ssid", "无线", "ac", "ap"]
        if "wifi" in scores and any(marker in text for marker in wifi_markers):
            scores["wifi"] = min(1.0, scores["wifi"] + 0.15)

        public_access_markers = ["公网", "上网", "nat", "不能访问公网", "禁止上网"]
        if "public_access" in scores and any(marker in text for marker in public_access_markers):
            scores["public_access"] = min(1.0, scores["public_access"] + 0.15)

        if not scores:
            return IntentResult(
                user_request=user_request,
                intent_type="unknown",
                confidence=0.0,
                supported=False,
                summary="",
                target_devices=target_devices,
                reason="未识别到已支持的网络配置或参考学习意图",
            )

        if "public_access" in scores and "vlan" in scores and any(marker in text for marker in public_access_markers):
            best_intent = "public_access"
        else:
            best_intent = max(scores, key=lambda intent: (scores[intent], _INTENT_PRIORITY.get(intent, 0)))

        if not target_devices:
            target_devices = _default_devices_for_intent(best_intent, device_names)

        summary = _INTENT_RULES[best_intent]["summary_tpl"].format(
            devices=", ".join(target_devices) if target_devices else "当前拓扑相关设备"
        )
        return IntentResult(
            user_request=user_request,
            intent_type=best_intent,
            confidence=round(scores[best_intent], 2),
            supported=True,
            summary=summary,
            target_devices=target_devices,
            reason="匹配关键词: " + ", ".join(matched_keywords[best_intent]),
        )


_default_parser: NlParser = RuleBasedParser()


def _load_device_names() -> list[str]:
    try:
        topo = parse_topology(get_topology_path())
        names = [device.name for device in topo.devices if device.name]
        if names:
            return names
    except Exception:
        pass

    try:
        return [str(device["name"]) for device in load_devices_yaml() if device.get("name")]
    except Exception:
        return []


def _default_devices_for_intent(intent_type: str, device_names: list[str]) -> list[str]:
    if intent_type == "dhcp":
        return [name for name in device_names if any(token in name.upper() for token in ("SW", "DHCP", "PC"))]
    if intent_type == "vlan":
        return [name for name in device_names if "SW" in name.upper()]
    if intent_type == "ospf":
        return [name for name in device_names if any(token in name.upper() for token in ("AR", "RT", "R"))]
    if intent_type == "pc_connectivity":
        return [name for name in device_names if any(token in name.upper() for token in ("PC", "AR", "RT", "FW"))]
    if intent_type == "ipsec_vpn":
        return [name for name in device_names if "FW" in name.upper() or "VPN" in name.upper()]
    if intent_type == "wifi":
        return [name for name in device_names if any(token in name.upper() for token in ("WIFI", "AC", "AP"))]
    if intent_type in {"access_control", "public_access"}:
        return [name for name in device_names if any(token in name.upper() for token in ("FW", "CORE", "SW"))]
    return device_names


def parse_intent(user_request: str) -> IntentResult:
    return _default_parser.parse(user_request)


def _draft_to_dict(draft: Any) -> Optional[dict[str, Any]]:
    if draft is None:
        return None
    return {
        "draft_id": draft.draft_id,
        "created_at": draft.created_at,
        "purpose": draft.purpose,
        "risk_summary": draft.risk_summary,
        "warnings": draft.warnings,
        "requires_confirmation": draft.requires_confirmation,
        "devices": [
            {
                "device_id": device.device_id,
                "device_name": device.device_name,
                "commands": device.commands,
                "purpose": device.purpose,
                "risk_level": device.risk_level,
                "risk_warning": device.risk_warning,
            }
            for device in draft.devices
        ],
    }


def _load_reference_context() -> dict[str, Any]:
    try:
        result = analyze_reference_configs()
    except Exception as exc:
        return {"success": False, "error": f"reference analysis failed: {exc}"}
    return result if isinstance(result, dict) else {"success": False, "error": "invalid reference analysis result"}


def _reference_context_for_intent(
    intent_type: str,
) -> tuple[list[str], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], list[str]]:
    reference = _load_reference_context()
    if not reference.get("success"):
        warning = reference.get("error", "参考配置分析不可用")
        return [], {}, {}, {}, {}, [f"参考配置未加载: {warning}"]

    patterns = reference.get("patterns", {})
    templates = reference.get("templates", {})
    drafts = reference.get("reference_drafts", {})
    capability_catalog = reference.get("capability_catalog", {})

    matched_pattern_names = _REFERENCE_PATTERN_MAP.get(intent_type, [])
    matched_template_names = _REFERENCE_TEMPLATE_MAP.get(intent_type, matched_pattern_names)
    matched_draft_names = _REFERENCE_DRAFT_MAP.get(intent_type, matched_pattern_names)

    details = {name: patterns.get(name) for name in matched_pattern_names if patterns.get(name)}
    selected_templates = {name: templates.get(name) for name in matched_template_names if templates.get(name)}
    selected_drafts = {name: drafts.get(name) for name in matched_draft_names if drafts.get(name)}
    selected_capabilities = {name: capability_catalog.get(name) for name in matched_template_names if capability_catalog.get(name)}

    return reference.get("knowledge_points", []), details, selected_templates, selected_drafts, selected_capabilities, []


def generate_nl_plan(
    user_request: str,
    adapter: BaseAdapter,
    diagnostics: list[DeviceDiagnostics],
    parser: Optional[NlParser] = None,
) -> NlPlanResponse:
    from backend.services.config_deploy_service import (
        generate_dhcp_draft,
        generate_ospf_draft,
        generate_pc_connectivity_draft,
        generate_vlan_draft,
    )
    from backend.services.connectivity_analysis import analyze_pc_connectivity

    parser = parser or _default_parser
    try:
        intent = parser.parse(user_request)
    except Exception as exc:
        return NlPlanResponse(
            user_request=user_request,
            intent_type="unknown",
            supported=False,
            summary="",
            target_devices=[],
            draft_type="none",
            confidence=0.0,
            error_message=f"解析失败: {type(exc).__name__}: {exc}",
            next_action="检查解析器后重试",
            reason="parser 异常",
        )

    if not intent.supported:
        return NlPlanResponse(
            user_request=user_request,
            intent_type=intent.intent_type,
            supported=False,
            summary="",
            target_devices=intent.target_devices,
            draft_type="none",
            confidence=intent.confidence,
            reason=intent.reason,
            next_action="请尝试 DHCP、OSPF、VLAN、PC 互通，或 IPSec/WiFi/ACL/NAT 参考学习类请求",
        )

    draft = None
    draft_type = _INTENT_RULES[intent.intent_type]["draft_type"]
    error_message = ""
    try:
        if intent.intent_type == "pc_connectivity":
            draft = generate_pc_connectivity_draft(adapter, analyze_pc_connectivity(diagnostics))
        elif intent.intent_type == "ospf":
            draft = generate_ospf_draft(adapter, diagnostics)
        elif intent.intent_type == "vlan":
            draft = generate_vlan_draft(adapter, diagnostics)
        elif intent.intent_type == "dhcp":
            draft = generate_dhcp_draft(adapter, diagnostics)
    except Exception as exc:
        error_message = f"草案生成失败: {type(exc).__name__}: {exc}"

    draft_dict = _draft_to_dict(draft)
    (
        reference_capabilities,
        reference_details,
        reference_templates,
        reference_drafts,
        protocol_capabilities,
        reference_warnings,
    ) = _reference_context_for_intent(intent.intent_type)

    matched_reference_patterns = list(reference_details.keys())
    warnings = list(reference_warnings)
    next_action = ""
    summary = intent.summary

    if error_message:
        summary = intent.summary + "（草案生成失败）"
        next_action = "请检查设备连接状态后重试"
    elif draft_type == "reference":
        if matched_reference_patterns:
            summary = intent.summary + "（已匹配当前实验参考配置）"
        primary_name = next(iter(reference_drafts), None)
        if primary_name:
            draft_dict = reference_drafts[primary_name]
        next_action = "当前已具备参考学习、模板提炼、候选命令草案和协议能力目录能力。"
    elif draft_dict is None:
        next_action = "当前配置可能已就绪，或该能力当前仅支持参考学习"
        if matched_reference_patterns:
            summary = intent.summary + "（未生成草案，但已关联参考配置模式）"
    else:
        warnings.extend(draft_dict.get("warnings", []))
        if matched_reference_patterns:
            warnings.append("已附加当前实验的参考配置模式、协议模板、候选命令草案和协议能力目录，可用于能力学习与方案校对。")
        next_action = "可查看 reference_templates / reference_drafts / protocol_capabilities 了解做法，不必落到具体 topo。"

    return NlPlanResponse(
        user_request=user_request,
        intent_type=intent.intent_type,
        supported=True,
        summary=summary,
        target_devices=intent.target_devices,
        draft_type=draft_type,
        confidence=intent.confidence,
        draft=draft_dict,
        warnings=warnings,
        next_action=next_action,
        reason=intent.reason,
        error_message=error_message,
        reference_capabilities=reference_capabilities,
        matched_reference_patterns=matched_reference_patterns,
        reference_details=reference_details,
        reference_templates=reference_templates,
        reference_drafts=reference_drafts,
        protocol_capabilities=protocol_capabilities,
    )
