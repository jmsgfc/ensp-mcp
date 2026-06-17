"""自然语言意图解析服务（MVP）。

职责：
1. 解析自然语言需求，识别意图类型
2. 提取目标设备
3. 路由到现有草案生成能力
4. 输出统一结构化响应

当前为规则版实现，不接入真实 LLM。

替换点说明：
- NlParser 协议定义了意图解析的抽象接口
- RuleBasedParser 是当前默认实现（关键词匹配）
- 未来接入真实 LLM 时，只需实现 NlParser 协议并注入 generate_nl_plan()
- 草案生成（generate_*_draft）和安全链路（confirmed/白名单/draft_id）不会被替换
"""

from dataclasses import dataclass, field, asdict
from typing import Optional, Protocol

from backend.adapters.base_adapter import BaseAdapter, DeviceDiagnostics
from backend.topology.validator import load_devices_yaml


# --- 数据模型 ---

@dataclass
class IntentResult:
    """意图识别结果。"""
    user_request: str
    intent_type: str  # "pc_connectivity" / "ospf" / "vlan" / "dhcp" / "unknown"
    confidence: float  # 0.0 ~ 1.0
    supported: bool
    summary: str
    target_devices: list[str] = field(default_factory=list)
    reason: str = ""


@dataclass
class NlPlanResponse:
    """自然语言配置计划响应。"""
    user_request: str
    intent_type: str
    supported: bool
    summary: str
    target_devices: list[str]
    draft_type: str  # "static_route" / "ospf" / "vlan" / "dhcp" / "none"
    confidence: float = 0.0
    draft: Optional[dict] = None
    warnings: list[str] = field(default_factory=list)
    next_action: str = ""
    reason: str = ""
    error_message: str = ""  # 草案生成失败时的错误信息，非空表示失败


# --- 解析器抽象 ---


class NlParser(Protocol):
    """自然语言意图解析器抽象接口。

    实现此协议即可替换 generate_nl_plan() 中的解析逻辑。
    当前默认实现为 RuleBasedParser（关键词匹配）。
    未来接入真实 LLM 时，实现此协议并传入 generate_nl_plan(parser=...) 即可。

    约束：
    - parse() 必须返回 IntentResult，不能抛异常
    - parse() 不能执行任何设备命令（只做"理解"，不做"执行"）
    - 返回的 IntentResult.intent_type 必须是已定义的类型之一
    """

    def parse(self, user_request: str) -> IntentResult:
        """解析自然语言需求，返回意图识别结果。"""
        ...


class RuleBasedParser:
    """规则版意图解析器（关键词匹配）。

    当前 MVP 默认实现。通过 _INTENT_RULES 中的关键词集合
    计算每个意图类型的匹配得分，取最高分作为识别结果。
    """

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

        # 提取目标设备；设备清单来自当前 devices.yaml，避免旧拓扑硬编码。
        device_names = _load_device_names()
        target_devices = [d for d in device_names if d.lower() in text]

        # 计算每个意图的得分
        scores: dict[str, float] = {}
        matched_keywords: dict[str, list[str]] = {}

        for intent_type, rule in _INTENT_RULES.items():
            hits = [kw for kw in rule["keywords"] if kw in text]
            if hits:
                raw_score = len(hits) / len(rule["keywords"])
                scores[intent_type] = max(0.5, min(1.0, raw_score + 0.3))
                matched_keywords[intent_type] = hits

        if not scores:
            return IntentResult(
                user_request=user_request,
                intent_type="unknown",
                confidence=0.0,
                supported=False,
                summary="",
                target_devices=target_devices,
                reason="未识别到已支持的网络配置意图",
            )

        best_intent = max(scores, key=scores.get)
        best_score = scores[best_intent]
        rule = _INTENT_RULES[best_intent]

        if not target_devices:
            target_devices = _default_devices_for_intent(best_intent, device_names)

        summary = rule["summary_tpl"].format(devices=", ".join(target_devices))

        return IntentResult(
            user_request=user_request,
            intent_type=best_intent,
            confidence=round(best_score, 2),
            supported=True,
            summary=summary,
            target_devices=target_devices,
            reason=f"匹配关键词: {', '.join(matched_keywords[best_intent])}",
        )


# 模块级默认解析器实例
_default_parser: NlParser = RuleBasedParser()


# --- 意图识别规则 ---

_INTENT_RULES: dict[str, dict] = {
    "pc_connectivity": {
        "keywords": ["pc1", "pc2", "互通", "连通", "ping", "静态路由", "pc1和pc2", "pc2和pc1"],
        "device_keywords": ["pc1", "pc2", "ar1", "ar2", "ar3"],
        "summary_tpl": "让 {devices} 之间网络互通（静态路由）",
        "draft_type": "static_route",
        "gen_func": "pc_connectivity",
    },
    "ospf": {
        "keywords": ["ospf", "路由协议", "三台路由器", "动态路由"],
        "device_keywords": ["ar1", "ar2", "ar3"],
        "summary_tpl": "为 {devices} 配置 OSPF 路由协议",
        "draft_type": "ospf",
        "gen_func": "ospf",
    },
    "vlan": {
        "keywords": ["vlan", "二层", "交换机"],
        "device_keywords": ["lsw1", "lsw2", "lsw3", "lsw4", "lsw5", "lsw6", "lsw7"],
        "summary_tpl": "为交换机配置 VLAN",
        "draft_type": "vlan",
        "gen_func": "vlan",
    },
    "dhcp": {
        "keywords": ["dhcp", "自动获取", "地址分配", "自动分配", "地址池"],
        "device_keywords": ["lsw1", "lsw2", "lsw3", "lsw4", "lsw5", "lsw6", "lsw7", "pc1", "pc2", "pc3", "pc4"],
        "summary_tpl": "配置 DHCP 地址分发，使 PC1/2/3/4 自动获取 IP",
        "draft_type": "dhcp",
        "gen_func": "dhcp",
    },
}

# 设备名到类型映射（用于提取目标设备）
def _load_device_names() -> list[str]:
    """Load current device names from devices.yaml for each parse call."""
    try:
        return [
            str(device["name"])
            for device in load_devices_yaml()
            if device.get("name")
        ]
    except Exception:
        return []


def _default_devices_for_intent(intent_type: str, device_names: list[str]) -> list[str]:
    """Build default target devices from the current device inventory."""
    names_lower = {name.lower(): name for name in device_names}
    if intent_type == "dhcp":
        return [
            name for name in device_names
            if name.upper().startswith(("LSW", "PC"))
        ]
    if intent_type == "vlan":
        return [
            name for name in device_names
            if name.upper().startswith("LSW")
        ]
    if intent_type in {"pc_connectivity", "ospf"}:
        return [
            name for name in device_names
            if name.upper().startswith(("AR", "PC"))
        ]
    return list(names_lower.values())


def parse_intent(user_request: str) -> IntentResult:
    """解析自然语言需求，识别意图类型。

    委托给模块级默认解析器（当前为 RuleBasedParser）。
    此函数保持向后兼容，外部调用无需修改。
    """
    return _default_parser.parse(user_request)


def _draft_to_dict(draft) -> Optional[dict]:
    """将 ConfigDraft dataclass 转为 dict（用于 JSON 响应）。"""
    if draft is None:
        return None
    result = {
        "draft_id": draft.draft_id,
        "created_at": draft.created_at,
        "purpose": draft.purpose,
        "risk_summary": draft.risk_summary,
        "warnings": draft.warnings,
        "requires_confirmation": draft.requires_confirmation,
        "devices": [],
    }
    for d in draft.devices:
        result["devices"].append({
            "device_id": d.device_id,
            "device_name": d.device_name,
            "commands": d.commands,
            "purpose": d.purpose,
            "risk_level": d.risk_level,
            "risk_warning": d.risk_warning,
        })
    return result


def generate_nl_plan(
    user_request: str,
    adapter: BaseAdapter,
    diagnostics: list[DeviceDiagnostics],
    parser: Optional[NlParser] = None,
) -> NlPlanResponse:
    """根据自然语言需求生成配置计划。

    流程：
    1. 调用 parser.parse() 识别意图（默认为 RuleBasedParser）
    2. 根据 intent_type 路由到对应 generate_*_draft()
    3. 将 ConfigDraft 转为 dict
    4. 构建 NlPlanResponse

    参数 parser：
    - 传入 NlParser 实现即可替换意图解析逻辑
    - 默认使用模块级 RuleBasedParser（关键词匹配）
    - 未来接入真实 LLM 时，实现 NlParser 协议并传入即可
    """
    from backend.services.config_deploy_service import (
        generate_pc_connectivity_draft,
        generate_ospf_draft,
        generate_vlan_draft,
        generate_dhcp_draft,
    )
    from backend.services.connectivity_analysis import analyze_pc_connectivity

    if parser is None:
        parser = _default_parser

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
            draft=None,
            error_message=f"解析失败: {type(exc).__name__}: {exc}",
            next_action="检查解析器或 LLM 服务状态后重试",
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
            next_action="请尝试以下类型的请求：PC1/PC2 互通、OSPF 配置、VLAN 配置、DHCP 地址分发",
        )

    # 路由到对应草案生成
    draft = None
    draft_type = "none"
    error_message = ""

    try:
        if intent.intent_type == "pc_connectivity":
            connectivity = analyze_pc_connectivity(diagnostics)
            draft = generate_pc_connectivity_draft(adapter, connectivity)
            draft_type = "static_route"

        elif intent.intent_type == "ospf":
            draft = generate_ospf_draft(adapter, diagnostics)
            draft_type = "ospf"

        elif intent.intent_type == "vlan":
            draft = generate_vlan_draft(adapter, diagnostics)
            draft_type = "vlan"

        elif intent.intent_type == "dhcp":
            draft = generate_dhcp_draft(adapter, diagnostics)
            draft_type = "dhcp"

    except Exception as exc:
        error_message = f"草案生成失败: {type(exc).__name__}: {exc}"

    draft_dict = _draft_to_dict(draft)

    # 构建响应
    warnings = []
    next_action = ""

    if error_message:
        summary = intent.summary + "（草案生成失败）"
        next_action = "请检查设备连接状态后重试"
    elif draft_dict is None:
        next_action = "当前配置已就绪，无需额外操作"
        summary = intent.summary + "（已就绪）"
    else:
        warnings = draft_dict.get("warnings", [])
        next_action = "可通过 POST /api/config/{type}/apply 执行配置下发"
        summary = intent.summary

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
    )
