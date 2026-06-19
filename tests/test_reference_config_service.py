from backend.services.reference_config_service import analyze_reference_configs


TOPO_XML = """<?xml version=\"1.0\" encoding=\"utf-8\"?>
<topo version=\"2.0\">
  <devices>
    <dev id=\"1\" name=\"Z-FW-1\" model=\"USG6000V\" />
    <dev id=\"2\" name=\"F-FW-1\" model=\"USG6000V\" />
    <dev id=\"3\" name=\"F-DHCP-Sercver\" model=\"AR2220\" />
    <dev id=\"4\" name=\"F-Core-SW1\" model=\"S5700\" />
    <dev id=\"5\" name=\"Z-WIFI-AC1\" model=\"AC6005\" />
    <dev id=\"6\" name=\"Z-Core-SW1\" model=\"S12700\" />
    <dev id=\"7\" name=\"Z-DataCenter-SW1\" model=\"S5700\" />
  </devices>
  <lines />
</topo>
"""

Z_FW_CFG = """
acl number 3001
 rule 5 permit ip source 10.10.10.0 0.0.0.255 destination 0.0.0.0 255.255.255.255
acl number 3000
 rule 5 permit ip source 10.10.0.0 0.0.255.255 destination 172.16.0.0 0.0.255.255
ipsec proposal ZB
 esp authentication-algorithm sha2-256
 ike proposal 5
  encryption-algorithm aes-256
ike peer branch
 remote-address 200.1.1.2
ipsec policy vpn-policy
interface GigabitEthernet1/0/0
 ipsec policy vpn-policy
interface Tunnel0
 tunnel-protocol gre
 source 200.1.1.1
 destination 200.1.1.2
nat-policy
 rule name inner_to_outer
  source-address 10.10.10.0 mask 255.255.255.0
  source-address 10.10.20.0 mask 255.255.255.0
  action source-nat easy-ip
ip route-static 172.16.0.0 255.255.0.0 200.1.1.2
"""

F_FW_CFG = """
acl number 3000
 rule 5 permit ip source 172.16.0.0 0.0.255.255 destination 10.10.0.0 0.0.255.255
ipsec proposal FB
 esp authentication-algorithm sha2-256
ike proposal 5
 encryption-algorithm aes-256
ike peer hq
 remote-address 200.1.1.1
ipsec policy vpn-policy-branch
interface GigabitEthernet1/0/0
 ipsec policy vpn-policy-branch
interface Tunnel0
 tunnel-protocol gre
 source 200.1.1.2
 destination 200.1.1.1
ip route-static 10.10.0.0 255.255.0.0 200.1.1.1
"""

F_DHCP_CFG = """
ip pool branch_users gateway-list 172.16.1.1 network 172.16.1.0 mask 255.255.255.0
"""

F_CORE_CFG = """
interface Vlanif10
 dhcp select relay
 dhcp relay server-ip 172.16.0.10
"""

Z_WIFI_CFG = """
interface Vlanif99
 ip address 10.10.99.1 255.255.255.0
interface Vlanif100
 ip address 10.10.100.1 255.255.255.0
interface Vlanif101
 ip address 10.10.101.1 255.255.255.0
capwap source interface vlanif99
wlan
 ssid-profile name ssid_guest
  ssid guestWiFi
 ssid-profile name ssid_enterprise
  ssid enterpriseWiFi
 vap-profile name vap_guest
  service-vlan vlan-id 101
 vap-profile name vap_enterprise
  service-vlan vlan-id 100
 ap-group name guest-AP
 ap-group name enterprise-AP
"""

Z_CORE_CFG = """
acl number 3050
 rule 5 deny ip source 10.10.101.0 0.0.0.255 destination 10.10.10.0 0.0.0.255
traffic-filter inbound acl 3050
ip pool vlan10
 gateway-list 10.10.10.254
 network 10.10.10.0 mask 255.255.255.0
interface Vlanif10
 ip address 10.10.10.1 255.255.255.0
 dhcp select global
interface Vlanif50
 ip address 10.10.50.1 255.255.255.0
"""

Z_DC_CFG = """
acl number 3000
 rule 5 deny ip source 10.10.101.0 0.0.0.255 destination 10.10.200.0 0.0.0.255
traffic-filter inbound acl 3000
"""


def test_analyze_reference_configs_extracts_patterns_templates_drafts_and_capabilities(monkeypatch, tmp_path):
    workspace_dir = tmp_path / "company-lab"
    workspace_dir.mkdir()
    (workspace_dir / "company-lab.topo").write_text(TOPO_XML, encoding="utf-8")

    config_dir = workspace_dir / "配置"
    config_dir.mkdir()
    (config_dir / "Z-FW-1.cfg").write_text(Z_FW_CFG, encoding="utf-8")
    (config_dir / "F-FW-1.cfg").write_text(F_FW_CFG, encoding="utf-8")
    (config_dir / "F-DHCP-Sercver.cfg").write_text(F_DHCP_CFG, encoding="utf-8")
    (config_dir / "F-Core-SW1.cfg").write_text(F_CORE_CFG, encoding="utf-8")
    (config_dir / "Z-WIFI-AC1.cfg").write_text(Z_WIFI_CFG, encoding="utf-8")
    (config_dir / "Z-Core-SW1.cfg").write_text(Z_CORE_CFG, encoding="utf-8")
    (config_dir / "Z-DataCenter-SW1.cfg").write_text(Z_DC_CFG, encoding="utf-8")

    monkeypatch.delenv("TOPOLOGY_FILE", raising=False)
    monkeypatch.setenv("ENSP_MCP_WORKSPACE_DIR", str(workspace_dir))

    result = analyze_reference_configs()

    assert result["success"] is True
    assert result["templates"]["ipsec_vpn"]["template_type"] == "site_to_site_ipsec_gre"
    assert result["templates"]["router_dhcp"]["template_type"] == "dhcp_pool_and_relay"
    assert result["templates"]["wifi"]["template_type"] == "ac_ssid_vlan_isolation"
    assert result["templates"]["access_control"]["template_type"] == "guest_acl_isolation"

    drafts = result["reference_drafts"]
    assert drafts["ipsec_vpn"]["reference_only"] is True
    assert any(device["device_name"] == "Z-FW-1" for device in drafts["ipsec_vpn"]["devices"])
    assert any("tunnel-protocol gre" in cmd for device in drafts["ipsec_vpn"]["devices"] for cmd in device["commands"])
    assert any("dhcp relay server-ip 172.16.0.10" in cmd for device in drafts["router_dhcp"]["devices"] for cmd in device["commands"])
    assert any("ssid guestWiFi" in cmd for device in drafts["wifi"]["devices"] for cmd in device["commands"])
    assert any("acl number 3050" in cmd for device in drafts["access_control"]["devices"] for cmd in device["commands"])
    assert any("nat-policy" in cmd for device in drafts["public_access"]["devices"] for cmd in device["commands"])

    capabilities = result["capability_catalog"]
    assert capabilities["ipsec_vpn"]["available"] is True
    assert "IKE peer 名称" in capabilities["ipsec_vpn"]["required_parameters"]
    assert capabilities["wifi"]["template_type"] == "ac_ssid_vlan_isolation"
    assert "traffic-filter inbound acl" in capabilities["access_control"]["validation_focus"]
    assert "nat-policy" in capabilities["public_access"]["validation_focus"]
