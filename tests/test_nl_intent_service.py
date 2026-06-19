from backend.services import nl_intent_service as service


class DummyAdapter:
    pass


def test_parse_intent_recognizes_ipsec_reference_learning(monkeypatch):
    monkeypatch.setattr(service, "_load_device_names", lambda: ["Z-FW-1", "F-FW-1", "Z-WIFI-AC1"])
    result = service.parse_intent("学习一下总部和分部的IPSec VPN和GRE隧道做法")
    assert result.supported is True
    assert result.intent_type == "ipsec_vpn"
    assert "Z-FW-1" in result.target_devices


def test_generate_nl_plan_returns_reference_draft_for_wifi(monkeypatch):
    monkeypatch.setattr(service, "_load_device_names", lambda: ["Z-WIFI-AC1", "AP1", "AP2"])
    monkeypatch.setattr(
        service,
        "analyze_reference_configs",
        lambda: {
            "success": True,
            "knowledge_points": ["无线 SSID、VLAN、AP 组下发参考", "访客隔离 ACL 参考"],
            "patterns": {
                "wifi": {"detected": True, "guest_vlan": "101", "enterprise_vlan": "100"},
                "access_control": {"detected": True, "guest_isolation_rules": [{"device": "Z-Core-SW1", "source": "10.10.101.0", "destination": "10.10.10.0"}]},
            },
            "templates": {
                "wifi": {"template_type": "ac_ssid_vlan_isolation"},
                "access_control": {"template_type": "guest_acl_isolation"},
            },
            "capability_catalog": {
                "wifi": {"available": True, "template_type": "ac_ssid_vlan_isolation", "required_parameters": ["SSID 名称"]},
                "access_control": {"available": True, "template_type": "guest_acl_isolation", "validation_focus": ["traffic-filter inbound acl"]},
            },
            "reference_drafts": {
                "wifi": {
                    "draft_id": "reference-wifi",
                    "reference_only": True,
                    "devices": [{"device_name": "Z-WIFI-AC1", "commands": ["wlan", "ssid guestWiFi"], "purpose": "wifi"}],
                    "warnings": ["reference only"],
                },
                "access_control": {
                    "draft_id": "reference-access_control",
                    "reference_only": True,
                    "devices": [{"device_name": "Z-Core-SW1", "commands": ["acl number 3050"], "purpose": "acl"}],
                    "warnings": [],
                },
            },
        },
    )

    plan = service.generate_nl_plan("学习访客WiFi自动下发和隔离做法", DummyAdapter(), [])

    assert plan.supported is True
    assert plan.intent_type == "wifi"
    assert plan.draft_type == "reference"
    assert plan.draft is not None
    assert plan.draft["draft_id"] == "reference-wifi"
    assert plan.reference_templates["wifi"]["template_type"] == "ac_ssid_vlan_isolation"
    assert plan.reference_drafts["access_control"]["devices"][0]["commands"] == ["acl number 3050"]
    assert plan.protocol_capabilities["wifi"]["template_type"] == "ac_ssid_vlan_isolation"
    assert plan.protocol_capabilities["access_control"]["available"] is True


def test_generate_nl_plan_keeps_dhcp_as_deployable_and_attaches_reference_assets(monkeypatch):
    monkeypatch.setattr(service, "_load_device_names", lambda: ["F-DHCP-Sercver", "F-Core-SW1", "PC1"])
    monkeypatch.setattr(
        service,
        "analyze_reference_configs",
        lambda: {
            "success": True,
            "knowledge_points": ["路由器/三层交换机 DHCP 与 Relay 参考"],
            "patterns": {"router_dhcp": {"detected": True, "devices": {"F-DHCP-Sercver": {"pool_count": 2}}}},
            "templates": {"router_dhcp": {"template_type": "dhcp_pool_and_relay"}},
            "capability_catalog": {"router_dhcp": {"available": True, "template_type": "dhcp_pool_and_relay", "required_parameters": ["地址池网段"]}},
            "reference_drafts": {
                "router_dhcp": {
                    "draft_id": "reference-router_dhcp",
                    "reference_only": True,
                    "devices": [{"device_name": "F-DHCP-Sercver", "commands": ["ip pool users"], "purpose": "dhcp"}],
                    "warnings": [],
                }
            },
        },
    )

    class DraftDevice:
        device_id = "1"
        device_name = "F-DHCP-Sercver"
        commands = ["ip pool users"]
        purpose = "dhcp"
        risk_level = "medium"
        risk_warning = ""

    class Draft:
        draft_id = "draft-1"
        created_at = "2026-06-20T10:00:00"
        purpose = "dhcp"
        risk_summary = "medium"
        warnings = []
        requires_confirmation = True
        devices = [DraftDevice()]

    monkeypatch.setitem(
        __import__("sys").modules,
        "backend.services.config_deploy_service",
        type(
            "M",
            (),
            {
                "generate_dhcp_draft": staticmethod(lambda adapter, diagnostics: Draft()),
                "generate_ospf_draft": staticmethod(lambda adapter, diagnostics: None),
                "generate_pc_connectivity_draft": staticmethod(lambda adapter, diagnostics: None),
                "generate_vlan_draft": staticmethod(lambda adapter, diagnostics: None),
            },
        )(),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "backend.services.connectivity_analysis",
        type("C", (), {"analyze_pc_connectivity": staticmethod(lambda diagnostics: None)})(),
    )

    plan = service.generate_nl_plan("请规划DHCP自动分配", DummyAdapter(), [])

    assert plan.supported is True
    assert plan.intent_type == "dhcp"
    assert plan.draft_type == "dhcp"
    assert plan.draft is not None
    assert plan.reference_templates["router_dhcp"]["template_type"] == "dhcp_pool_and_relay"
    assert plan.reference_drafts["router_dhcp"]["devices"][0]["commands"] == ["ip pool users"]
    assert plan.protocol_capabilities["router_dhcp"]["template_type"] == "dhcp_pool_and_relay"


def test_parse_intent_recognizes_public_access_even_with_vlan_wording(monkeypatch):
    monkeypatch.setattr(service, "_load_device_names", lambda: ["Z-FW-1", "Z-Core-SW1", "Z-Core-SW2"])
    result = service.parse_intent("学习总部哪些VLAN不能访问公网")
    assert result.supported is True
    assert result.intent_type == "public_access"
