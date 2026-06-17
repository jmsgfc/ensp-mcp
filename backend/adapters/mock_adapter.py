"""Mock 设备适配器。

返回模拟设备数据和模拟命令执行结果，用于开发调试阶段。
不依赖真实 eNSP 连接。
"""

from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

from backend.adapters.base_adapter import (
    BackupResult,
    BaseAdapter,
    CommandOutput,
    CommandResult,
    ConfigCommandResult,
    DeviceConnectionError,
    DeviceDiagnostics,
    DeviceInfo,
    DeviceNotFoundError,
    DeviceStatus,
    PcDhcpStatus,
    RestoreResult,
    SaveResult,
)
from backend.topology.config import get_backups_dir, get_devices_config_path
from backend.topology.models import DeviceTopoInfo, TopologyData
from backend.topology.parser import parse_topology
from backend.utils.security import check_command


# 模拟命令输出
_MOCK_OUTPUTS: dict[str, dict[str, str]] = {
    "display interface brief": {
        "AR1": (
            "Interface                   PHY   Protocol  InOutUti\n"
            "GE0/0/0                     up    up        0%  0%\n"
            "GE0/0/1                     up    up        0%  0%\n"
            "GE0/0/2                     up    up        0%  0%\n"
            "NULL0                       up    up(s)     0%  0%"
        ),
        "AR2": (
            "Interface                   PHY   Protocol  InOutUti\n"
            "GE0/0/0                     up    up        0%  0%\n"
            "GE0/0/1                     up    up        0%  0%\n"
            "GE0/0/2                     up    up        0%  0%\n"
            "NULL0                       up    up(s)     0%  0%"
        ),
        "AR3": (
            "Interface                   PHY   Protocol  InOutUti\n"
            "GE0/0/0                     up    up        0%  0%\n"
            "GE0/0/1                     up    up        0%  0%\n"
            "GE0/0/2                     up    up        0%  0%\n"
            "NULL0                       up    up(s)     0%  0%"
        ),
        "LSW1": (
            "Interface                   PHY   Protocol  InOutUti\n"
            "GE0/0/0                     up    up        0%  0%\n"
            "GE0/0/1                     up    up        0%  0%\n"
            "GE0/0/2                     up    up        0%  0%\n"
            "GE0/0/3                     up    up        0%  0%\n"
            "NULL0                       up    up(s)     0%  0%"
        ),
        "LSW2": (
            "Interface                   PHY   Protocol  InOutUti\n"
            "GE0/0/0                     up    up        0%  0%\n"
            "GE0/0/1                     up    up        0%  0%\n"
            "GE0/0/2                     up    up        0%  0%\n"
            "NULL0                       up    up(s)     0%  0%"
        ),
        "LSW3": (
            "Interface                   PHY   Protocol  InOutUti\n"
            "GE0/0/0                     up    up        0%  0%\n"
            "GE0/0/1                     up    up        0%  0%\n"
            "GE0/0/2                     up    up        0%  0%\n"
            "NULL0                       up    up(s)     0%  0%"
        ),
        "LSW4": (
            "Interface                   PHY   Protocol  InOutUti\n"
            "GE0/0/0                     up    up        0%  0%\n"
            "GE0/0/1                     up    up        0%  0%\n"
            "GE0/0/2                     up    up        0%  0%\n"
            "NULL0                       up    up(s)     0%  0%"
        ),
    },
    "display ip interface brief": {
        "AR1": (
            "Interface                         IP Address      Method   Status\n"
            "GE0/0/0                           192.168.1.1     manual   up\n"
            "GE0/0/1                           10.0.12.1       manual   up\n"
            "GE0/0/2                           10.0.13.1       manual   up"
        ),
        "AR2": (
            "Interface                         IP Address      Method   Status\n"
            "GE0/0/0                           192.168.2.1     manual   up\n"
            "GE0/0/1                           10.0.12.2       manual   up\n"
            "GE0/0/2                           unassigned      DHCP     down"
        ),
        "AR3": (
            "Interface                         IP Address      Method   Status\n"
            "GE0/0/0                           192.168.3.1     manual   up\n"
            "GE0/0/1                           10.0.13.2       manual   up\n"
            "GE0/0/2                           unassigned      DHCP     down"
        ),
    },
    "display ip routing-table": {
        "AR1": (
            "Route Flags: R - relay, D - download to fib\n"
            "------------------------------------------------------------------------------\n"
            "Routing Tables: Public\n"
            "         Destinations : 5        Routes : 5\n"
            "Destination/Mask    Proto  Pre  Cost     Flags NextHop         Interface\n"
            "10.0.12.0/24        Direct 0    0           D  10.0.12.1       GE0/0/1\n"
            "10.0.13.0/24        Direct 0    0           D  10.0.13.1       GE0/0/2\n"
            "192.168.1.0/24      Direct 0    0           D  192.168.1.1     GE0/0/0\n"
            "192.168.2.0/24      OSPF   10   2           D  10.0.12.2       GE0/0/1\n"
            "192.168.3.0/24      OSPF   10   2           D  10.0.13.2       GE0/0/2"
        ),
        "AR2": (
            "Route Flags: R - relay, D - download to fib\n"
            "------------------------------------------------------------------------------\n"
            "Routing Tables: Public\n"
            "         Destinations : 4        Routes : 4\n"
            "Destination/Mask    Proto  Pre  Cost     Flags NextHop         Interface\n"
            "10.0.12.0/24        Direct 0    0           D  10.0.12.2       GE0/0/1\n"
            "192.168.1.0/24      OSPF   10   2           D  10.0.12.1       GE0/0/1\n"
            "192.168.2.0/24      Direct 0    0           D  192.168.2.1     GE0/0/0\n"
            "192.168.3.0/24      OSPF   10   3           D  10.0.12.1       GE0/0/1"
        ),
        "AR3": (
            "Route Flags: R - relay, D - download to fib\n"
            "------------------------------------------------------------------------------\n"
            "Routing Tables: Public\n"
            "         Destinations : 4        Routes : 4\n"
            "Destination/Mask    Proto  Pre  Cost     Flags NextHop         Interface\n"
            "10.0.13.0/24        Direct 0    0           D  10.0.13.2       GE0/0/1\n"
            "192.168.1.0/24      OSPF   10   2           D  10.0.13.1       GE0/0/1\n"
            "192.168.2.0/24      OSPF   10   3           D  10.0.13.1       GE0/0/1\n"
            "192.168.3.0/24      Direct 0    0           D  192.168.3.1     GE0/0/0"
        ),
    },
    "display current-configuration": {
        "AR1": (
            "#\n"
            "sysname AR1\n"
            "#\n"
            "interface GigabitEthernet0/0/0\n"
            " ip address 192.168.1.1 255.255.255.0\n"
            "#\n"
            "interface GigabitEthernet0/0/1\n"
            " ip address 10.0.12.1 255.255.255.0\n"
            "#\n"
            "interface GigabitEthernet0/0/2\n"
            " ip address 10.0.13.1 255.255.255.0\n"
            "#\n"
            "return"
        ),
        "AR2": (
            "#\n"
            "sysname AR2\n"
            "#\n"
            "interface GigabitEthernet0/0/0\n"
            " ip address 192.168.2.1 255.255.255.0\n"
            "#\n"
            "interface GigabitEthernet0/0/1\n"
            " ip address 10.0.12.2 255.255.255.0\n"
            "#\n"
            "return"
        ),
        "AR3": (
            "#\n"
            "sysname AR3\n"
            "#\n"
            "interface GigabitEthernet0/0/0\n"
            " ip address 192.168.3.1 255.255.255.0\n"
            "#\n"
            "interface GigabitEthernet0/0/1\n"
            " ip address 10.0.13.2 255.255.255.0\n"
            "#\n"
            "return"
        ),
        "LSW1": (
            "#\n"
            "sysname LSW1\n"
            "#\n"
            "return"
        ),
        "LSW2": (
            "#\n"
            "sysname LSW2\n"
            "#\n"
            "return"
        ),
        "LSW3": (
            "#\n"
            "sysname LSW3\n"
            "#\n"
            "return"
        ),
        "LSW4": (
            "#\n"
            "sysname LSW4\n"
            "#\n"
            "return"
        ),
    },
    "display ospf peer": {
        "AR1": (
            "OSPF Process 1 with Router ID 192.168.1.1\n"
            "Neighbor Brief Information\n"
            "Area 0.0.0.0\n"
            "Router ID       Address         Pri  Dead-Time  State      Interface\n"
            "10.0.12.2       10.0.12.2       1    35         Full       GE0/0/1\n"
            "10.0.13.2       10.0.13.2       1    36         Full       GE0/0/2"
        ),
        "AR2": (
            "OSPF Process 1 with Router ID 10.0.12.2\n"
            "Neighbor Brief Information\n"
            "Area 0.0.0.0\n"
            "Router ID       Address         Pri  Dead-Time  State      Interface\n"
            "192.168.1.1     10.0.12.1       1    34         Full       GE0/0/1"
        ),
        "AR3": (
            "OSPF Process 1 with Router ID 10.0.13.2\n"
            "Neighbor Brief Information\n"
            "Area 0.0.0.0\n"
            "Router ID       Address         Pri  Dead-Time  State      Interface\n"
            "192.168.1.1     10.0.13.1       1    33         Full       GE0/0/1"
        ),
    },
    "display ospf brief": {
        "AR1": (
            "OSPF Process 1 with Router ID 192.168.1.1\n"
            "OSPF Protocol Information\n"
            "RouterID: 192.168.1.1   Area: 0.0.0.0\n"
            "SPF Scheduled Count: 3\n"
            "Area: 0.0.0.0\n"
            "Interface          State  Cost  Pri\n"
            "GE0/0/0            DR     1     1\n"
            "GE0/0/1            DR     1     1\n"
            "GE0/0/2            DR     1     1"
        ),
        "AR2": (
            "OSPF Process 1 with Router ID 10.0.12.2\n"
            "OSPF Protocol Information\n"
            "RouterID: 10.0.12.2   Area: 0.0.0.0\n"
            "SPF Scheduled Count: 2\n"
            "Area: 0.0.0.0\n"
            "Interface          State  Cost  Pri\n"
            "GE0/0/0            DR     1     1\n"
            "GE0/0/1            BDR    1     1"
        ),
        "AR3": (
            "OSPF Process 1 with Router ID 10.0.13.2\n"
            "OSPF Protocol Information\n"
            "RouterID: 10.0.13.2   Area: 0.0.0.0\n"
            "SPF Scheduled Count: 2\n"
            "Area: 0.0.0.0\n"
            "Interface          State  Cost  Pri\n"
            "GE0/0/0            DR     1     1\n"
            "GE0/0/1            BDR    1     1"
        ),
    },
    "display vlan": {
        "AR1": (
            "The total number of VLANs is: 2\n"
            "--------------------------------------------------------------------------------\n"
            "U: Up;         D: Down;         TK: Tracked;         ADJ: Adjusted;\n"
            "--------------------------------------------------------------------------------\n"
            "VID  Type    Ports\n"
            "--------------------------------------------------------------------------------\n"
            "1    common  UT:GE0/0/0(U)     GE0/0/1(U)     GE0/0/2(U)\n"
            "10   common  UT:GE0/0/0(U)\n"
            "--------------------------------------------------------------------------------"
        ),
        "AR2": (
            "The total number of VLANs is: 2\n"
            "--------------------------------------------------------------------------------\n"
            "U: Up;         D: Down;         TK: Tracked;         ADJ: Adjusted;\n"
            "--------------------------------------------------------------------------------\n"
            "VID  Type    Ports\n"
            "--------------------------------------------------------------------------------\n"
            "1    common  UT:GE0/0/0(U)     GE0/0/1(U)     GE0/0/2(U)\n"
            "10   common  UT:GE0/0/0(U)\n"
            "--------------------------------------------------------------------------------"
        ),
        "AR3": (
            "The total number of VLANs is: 2\n"
            "--------------------------------------------------------------------------------\n"
            "U: Up;         D: Down;         TK: Tracked;         ADJ: Adjusted;\n"
            "--------------------------------------------------------------------------------\n"
            "VID  Type    Ports\n"
            "--------------------------------------------------------------------------------\n"
            "1    common  UT:GE0/0/0(U)     GE0/0/1(U)     GE0/0/2(U)\n"
            "10   common  UT:GE0/0/0(U)\n"
            "--------------------------------------------------------------------------------"
        ),
        "LSW1": (
            "The total number of VLANs is: 1\n"
            "--------------------------------------------------------------------------------\n"
            "VID  Type    Ports\n"
            "--------------------------------------------------------------------------------\n"
            "1    common  UT:GE0/0/0(U)     GE0/0/1(U)     GE0/0/2(U)     GE0/0/3(U)\n"
            "--------------------------------------------------------------------------------"
        ),
        "LSW2": (
            "The total number of VLANs is: 1\n"
            "--------------------------------------------------------------------------------\n"
            "VID  Type    Ports\n"
            "--------------------------------------------------------------------------------\n"
            "1    common  UT:GE0/0/0(U)     GE0/0/1(U)     GE0/0/2(U)\n"
            "--------------------------------------------------------------------------------"
        ),
        "LSW3": (
            "The total number of VLANs is: 1\n"
            "--------------------------------------------------------------------------------\n"
            "VID  Type    Ports\n"
            "--------------------------------------------------------------------------------\n"
            "1    common  UT:GE0/0/0(U)     GE0/0/1(U)     GE0/0/2(U)\n"
            "--------------------------------------------------------------------------------"
        ),
        "LSW4": (
            "The total number of VLANs is: 1\n"
            "--------------------------------------------------------------------------------\n"
            "VID  Type    Ports\n"
            "--------------------------------------------------------------------------------\n"
            "1    common  UT:GE0/0/0(U)     GE0/0/1(U)     GE0/0/2(U)\n"
            "--------------------------------------------------------------------------------"
        ),
    },
    "display version": {
        "AR1": (
            "Huawei Versatile Routing Platform Software\n"
            "VRP (R) software, Version 5.170 (AR2220 V200R003C00SPC200)\n"
            "Copyright (C) 2011-2018 HUAWEI TECH CO., LTD\n"
            "HUAWEI AR2220 uptime is 0 week, 1 day, 3 hours, 25 minutes"
        ),
        "AR2": (
            "Huawei Versatile Routing Platform Software\n"
            "VRP (R) software, Version 5.170 (AR2220 V200R003C00SPC200)\n"
            "Copyright (C) 2011-2018 HUAWEI TECH CO., LTD\n"
            "HUAWEI AR2220 uptime is 0 week, 0 days, 12 hours, 10 minutes"
        ),
        "AR3": (
            "Huawei Versatile Routing Platform Software\n"
            "VRP (R) software, Version 5.170 (AR2220 V200R003C00SPC200)\n"
            "Copyright (C) 2011-2018 HUAWEI TECH CO., LTD\n"
            "HUAWEI AR2220 uptime is 0 week, 2 days, 6 hours, 45 minutes"
        ),
        "LSW1": (
            "Huawei Versatile Routing Platform Software\n"
            "VRP (R) software, Version 5.170 (S5700 V200R003C00SPC200)\n"
            "Copyright (C) 2011-2018 HUAWEI TECH CO., LTD\n"
            "HUAWEI S5700 uptime is 0 week, 1 day, 5 hours, 10 minutes"
        ),
        "LSW2": (
            "Huawei Versatile Routing Platform Software\n"
            "VRP (R) software, Version 5.170 (S3700 V200R003C00SPC200)\n"
            "Copyright (C) 2011-2018 HUAWEI TECH CO., LTD\n"
            "HUAWEI S3700 uptime is 0 week, 0 days, 8 hours, 20 minutes"
        ),
        "LSW3": (
            "Huawei Versatile Routing Platform Software\n"
            "VRP (R) software, Version 5.170 (S3700 V200R003C00SPC200)\n"
            "Copyright (C) 2011-2018 HUAWEI TECH CO., LTD\n"
            "HUAWEI S3700 uptime is 0 week, 0 days, 6 hours, 15 minutes"
        ),
        "LSW4": (
            "Huawei Versatile Routing Platform Software\n"
            "VRP (R) software, Version 5.170 (S3700 V200R003C00SPC200)\n"
            "Copyright (C) 2011-2018 HUAWEI TECH CO., LTD\n"
            "HUAWEI S3700 uptime is 0 week, 0 days, 4 hours, 30 minutes"
        ),
    },
    "display ip pool": {
        "LSW1": (
            "  Pool-name      : vlan10\n"
            "  Pool-No        : 0\n"
            "  Lease          : 1 Days 0 Hours 0 Minutes\n"
            "  Position       : Local\n"
            "  Status         : Unlocked\n"
            "  Gateway        : 192.168.10.1\n"
            "  Network        : 192.168.10.0\n"
            "  Mask           : 255.255.255.0\n"
            "  VPN instance   : --\n"
            "--------------------------------------------------------------------------------\n"
            "  Pool-name      : vlan20\n"
            "  Pool-No        : 1\n"
            "  Lease          : 1 Days 0 Hours 0 Minutes\n"
            "  Position       : Local\n"
            "  Status         : Unlocked\n"
            "  Gateway        : 192.168.20.1\n"
            "  Network        : 192.168.20.0\n"
            "  Mask           : 255.255.255.0\n"
            "  VPN instance   : --\n"
            "--------------------------------------------------------------------------------\n"
            "  Pool-name      : vlan30\n"
            "  Pool-No        : 2\n"
            "  Lease          : 1 Days 0 Hours 0 Minutes\n"
            "  Position       : Local\n"
            "  Status         : Unlocked\n"
            "  Gateway        : 192.168.30.1\n"
            "  Network        : 192.168.30.0\n"
            "  Mask           : 255.255.255.0\n"
            "  VPN instance   : --"
        ),
        "LSW2": ("Info: No IP pool found."),
        "LSW3": ("Info: No IP pool found."),
        "LSW4": ("Info: No IP pool found."),
    },
    "display dhcp statistics": {
        "LSW1": (
            "DHCP server statistic:\n"
            "  Global lease request       : 0\n"
            "  Global lease assigned      : 0\n"
            "  Global lease declined      : 0\n"
            "  Global lease released      : 0"
        ),
        "LSW2": ("DHCP is not enabled."),
        "LSW3": ("DHCP is not enabled."),
        "LSW4": ("DHCP is not enabled."),
    },
}

# 默认输出模板
_DEFAULT_OUTPUT = "模拟设备已收到命令: {command}"

# DHCP 配置状态标志（draft 执行后切换为 True）
_dhcp_config_applied = False

# PC DHCP 期望地址（Mock 模式下 DHCP 配置成功后 PC 应获取到的地址）
_EXPECTED_PCS: dict[str, dict[str, object]] = {
    "PC1": {"ip": "192.168.10.100", "mask": "255.255.255.0", "gateway": "192.168.10.1", "dhcp_state": 1},
    "PC2": {"ip": "192.168.20.100", "mask": "255.255.255.0", "gateway": "192.168.20.1", "dhcp_state": 1},
    "PC3": {"ip": "192.168.30.100", "mask": "255.255.255.0", "gateway": "192.168.30.1", "dhcp_state": 1},
    "PC4": {"ip": "192.168.40.100", "mask": "255.255.255.0", "gateway": "192.168.40.1", "dhcp_state": 1},
}


def set_dhcp_applied() -> None:
    """标记 DHCP 配置已应用（切换 mock 输出到已配置状态）。"""
    global _dhcp_config_applied
    _dhcp_config_applied = True


def clear_dhcp_state() -> None:
    """重置 DHCP 配置状态（测试隔离用）。"""
    global _dhcp_config_applied
    _dhcp_config_applied = False

# DHCP 配置已应用后的 switch mock 输出
_MOCK_OUTPUTS_DHCP_APPLIED: dict[str, dict[str, str]] = {
    "display vlan": {
        "LSW1": (
            "The total number of VLANs is: 5\n"
            "--------------------------------------------------------------------------------\n"
            "VID  Type    Ports\n"
            "--------------------------------------------------------------------------------\n"
            "1    common  UT:GE0/0/0(U)\n"
            "10   common  TG:GE0/0/1(U)   GE0/0/2(U)\n"
            "20   common  TG:GE0/0/1(U)   GE0/0/2(U)\n"
            "30   common  TG:GE0/0/1(U)   GE0/0/2(U)\n"
            "40   common  TG:GE0/0/1(U)   GE0/0/2(U)\n"
            "--------------------------------------------------------------------------------"
        ),
        "LSW6": (
            "The total number of VLANs is: 5\n"
            "--------------------------------------------------------------------------------\n"
            "VID  Type    Ports\n"
            "--------------------------------------------------------------------------------\n"
            "1    common  UT:Eth0/0/1(U)\n"
            "10   common  TG:Eth0/0/1(U)   Eth0/0/2(U)   Eth0/0/3(U)\n"
            "20   common  TG:Eth0/0/1(U)   Eth0/0/2(U)   Eth0/0/3(U)\n"
            "30   common  TG:Eth0/0/1(U)   Eth0/0/2(U)   Eth0/0/3(U)\n"
            "40   common  TG:Eth0/0/1(U)   Eth0/0/2(U)   Eth0/0/3(U)\n"
            "--------------------------------------------------------------------------------"
        ),
        "LSW7": (
            "The total number of VLANs is: 5\n"
            "--------------------------------------------------------------------------------\n"
            "VID  Type    Ports\n"
            "--------------------------------------------------------------------------------\n"
            "1    common  UT:Eth0/0/1(U)\n"
            "10   common  TG:Eth0/0/1(U)   Eth0/0/2(U)   Eth0/0/3(U)\n"
            "20   common  TG:Eth0/0/1(U)   Eth0/0/2(U)   Eth0/0/3(U)\n"
            "30   common  TG:Eth0/0/1(U)   Eth0/0/2(U)   Eth0/0/3(U)\n"
            "40   common  TG:Eth0/0/1(U)   Eth0/0/2(U)   Eth0/0/3(U)\n"
            "--------------------------------------------------------------------------------"
        ),
        "LSW5": (
            "The total number of VLANs is: 2\n"
            "--------------------------------------------------------------------------------\n"
            "VID  Type    Ports\n"
            "--------------------------------------------------------------------------------\n"
            "1    common  UT:Eth0/0/1(U)\n"
            "10   common  UT:Eth0/0/2(U)   TG:Eth0/0/1(U)\n"
            "--------------------------------------------------------------------------------"
        ),
        "LSW2": (
            "The total number of VLANs is: 2\n"
            "--------------------------------------------------------------------------------\n"
            "VID  Type    Ports\n"
            "--------------------------------------------------------------------------------\n"
            "1    common  UT:Eth0/0/1(U)\n"
            "20   common  UT:Eth0/0/2(U)   TG:Eth0/0/1(U)\n"
            "--------------------------------------------------------------------------------"
        ),
        "LSW3": (
            "The total number of VLANs is: 2\n"
            "--------------------------------------------------------------------------------\n"
            "VID  Type    Ports\n"
            "--------------------------------------------------------------------------------\n"
            "1    common  UT:Eth0/0/1(U)\n"
            "30   common  UT:Eth0/0/2(U)   TG:Eth0/0/1(U)\n"
            "--------------------------------------------------------------------------------"
        ),
        "LSW4": (
            "The total number of VLANs is: 2\n"
            "--------------------------------------------------------------------------------\n"
            "VID  Type    Ports\n"
            "--------------------------------------------------------------------------------\n"
            "1    common  UT:Eth0/0/1(U)\n"
            "40   common  UT:Eth0/0/2(U)   TG:Eth0/0/3(U)\n"
            "--------------------------------------------------------------------------------"
        ),
    },
    "display current-configuration": {
        "LSW1": (
            "#\n"
            "sysname LSW1\n"
            "#\n"
            "vlan batch 10 20 30 40\n"
            "#\n"
            "dhcp enable\n"
            "#\n"
            "interface Vlanif10\n"
            " ip address 192.168.10.1 255.255.255.0\n"
            " dhcp select global\n"
            "#\n"
            "interface Vlanif20\n"
            " ip address 192.168.20.1 255.255.255.0\n"
            " dhcp select global\n"
            "#\n"
            "interface Vlanif30\n"
            " ip address 192.168.30.1 255.255.255.0\n"
            " dhcp select global\n"
            "#\n"
            "interface Vlanif40\n"
            " ip address 192.168.40.1 255.255.255.0\n"
            " dhcp select global\n"
            "#\n"
            "interface GigabitEthernet0/0/1\n"
            " port link-type trunk\n"
            " port trunk allow-pass vlan 10 20 30 40\n"
            "#\n"
            "interface GigabitEthernet0/0/2\n"
            " port link-type trunk\n"
            " port trunk allow-pass vlan 10 20 30 40\n"
            "#\n"
            "ip pool vlan10\n"
            " network 192.168.10.0 mask 255.255.255.0\n"
            " gateway-list 192.168.10.1\n"
            "#\n"
            "ip pool vlan20\n"
            " network 192.168.20.0 mask 255.255.255.0\n"
            " gateway-list 192.168.20.1\n"
            "#\n"
            "ip pool vlan30\n"
            " network 192.168.30.0 mask 255.255.255.0\n"
            " gateway-list 192.168.30.1\n"
            "#\n"
            "ip pool vlan40\n"
            " network 192.168.40.0 mask 255.255.255.0\n"
            " gateway-list 192.168.40.1\n"
            "#\n"
            "return"
        ),
        "LSW6": (
            "#\n"
            "sysname LSW6\n"
            "#\n"
            "vlan batch 10 20 30 40\n"
            "#\n"
            "interface Ethernet0/0/1\n"
            " port link-type trunk\n"
            " port trunk allow-pass vlan 10 20 30 40\n"
            "#\n"
            "interface Ethernet0/0/2\n"
            " port link-type trunk\n"
            " port trunk allow-pass vlan 10 20 30 40\n"
            "#\n"
            "interface Ethernet0/0/3\n"
            " port link-type trunk\n"
            " port trunk allow-pass vlan 10 20 30 40\n"
            "#\n"
            "return"
        ),
        "LSW7": (
            "#\n"
            "sysname LSW7\n"
            "#\n"
            "vlan batch 10 20 30 40\n"
            "#\n"
            "interface Ethernet0/0/1\n"
            " port link-type trunk\n"
            " port trunk allow-pass vlan 10 20 30 40\n"
            "#\n"
            "interface Ethernet0/0/2\n"
            " port link-type trunk\n"
            " port trunk allow-pass vlan 10 20 30 40\n"
            "#\n"
            "interface Ethernet0/0/3\n"
            " port link-type trunk\n"
            " port trunk allow-pass vlan 10 20 30 40\n"
            "#\n"
            "return"
        ),
        "LSW5": (
            "#\n"
            "sysname LSW5\n"
            "#\n"
            "vlan batch 10\n"
            "#\n"
            "interface Ethernet0/0/1\n"
            " port link-type trunk\n"
            " port trunk allow-pass vlan 10 20 30 40\n"
            "#\n"
            "interface Ethernet0/0/2\n"
            " port link-type access\n"
            " port default vlan 10\n"
            "#\n"
            "return"
        ),
        "LSW2": (
            "#\n"
            "sysname LSW2\n"
            "#\n"
            "vlan batch 20\n"
            "#\n"
            "interface Ethernet0/0/1\n"
            " port link-type trunk\n"
            " port trunk allow-pass vlan 10 20 30 40\n"
            "#\n"
            "interface Ethernet0/0/2\n"
            " port link-type access\n"
            " port default vlan 20\n"
            "#\n"
            "return"
        ),
        "LSW3": (
            "#\n"
            "sysname LSW3\n"
            "#\n"
            "vlan batch 30\n"
            "#\n"
            "interface Ethernet0/0/1\n"
            " port link-type trunk\n"
            " port trunk allow-pass vlan 10 20 30 40\n"
            "#\n"
            "interface Ethernet0/0/2\n"
            " port link-type access\n"
            " port default vlan 30\n"
            "#\n"
            "return"
        ),
        "LSW4": (
            "#\n"
            "sysname LSW4\n"
            "#\n"
            "vlan batch 40\n"
            "#\n"
            "interface Ethernet0/0/2\n"
            " port link-type access\n"
            " port default vlan 40\n"
            "#\n"
            "interface Ethernet0/0/3\n"
            " port link-type trunk\n"
            " port trunk allow-pass vlan 10 20 30 40\n"
            "#\n"
            "return"
        ),
    },
    "display ip pool": {
        "LSW1": (
            "  Pool-name      : vlan10\n"
            "  Pool-No        : 0\n"
            "  Lease          : 1 Days 0 Hours 0 Minutes\n"
            "  Position       : Local\n"
            "  Status         : Unlocked\n"
            "  Gateway        : 192.168.10.1\n"
            "  Network        : 192.168.10.0\n"
            "  Mask           : 255.255.255.0\n"
            "  VPN instance   : --\n"
            "--------------------------------------------------------------------------------\n"
            "  Pool-name      : vlan20\n"
            "  Pool-No        : 1\n"
            "  Lease          : 1 Days 0 Hours 0 Minutes\n"
            "  Position       : Local\n"
            "  Status         : Unlocked\n"
            "  Gateway        : 192.168.20.1\n"
            "  Network        : 192.168.20.0\n"
            "  Mask           : 255.255.255.0\n"
            "  VPN instance   : --\n"
            "--------------------------------------------------------------------------------\n"
            "  Pool-name      : vlan30\n"
            "  Pool-No        : 2\n"
            "  Lease          : 1 Days 0 Hours 0 Minutes\n"
            "  Position       : Local\n"
            "  Status         : Unlocked\n"
            "  Gateway        : 192.168.30.1\n"
            "  Network        : 192.168.30.0\n"
            "  Mask           : 255.255.255.0\n"
            "  VPN instance   : --\n"
            "--------------------------------------------------------------------------------\n"
            "  Pool-name      : vlan40\n"
            "  Pool-No        : 3\n"
            "  Lease          : 1 Days 0 Hours 0 Minutes\n"
            "  Position       : Local\n"
            "  Status         : Unlocked\n"
            "  Gateway        : 192.168.40.1\n"
            "  Network        : 192.168.40.0\n"
            "  Mask           : 255.255.255.0\n"
            "  VPN instance   : --"
        ),
        "LSW6": ("Info: No IP pool found."),
        "LSW7": ("Info: No IP pool found."),
        "LSW5": ("Info: No IP pool found."),
        "LSW2": ("Info: No IP pool found."),
        "LSW3": ("Info: No IP pool found."),
        "LSW4": ("Info: No IP pool found."),
    },
    "display dhcp statistics": {
        "LSW1": (
            "DHCP server statistic:\n"
            "  Global lease request       : 0\n"
            "  Global lease assigned      : 0\n"
            "  Global lease declined      : 0\n"
            "  Global lease released      : 0"
        ),
        "LSW6": ("DHCP is not enabled."),
        "LSW7": ("DHCP is not enabled."),
        "LSW5": ("DHCP is not enabled."),
        "LSW2": ("DHCP is not enabled."),
        "LSW3": ("DHCP is not enabled."),
        "LSW4": ("DHCP is not enabled."),
    },
}


def _get_mock_output(device_name: str, command: str) -> str:
    """获取模拟输出。优先精确匹配，否则返回默认输出。"""
    cmd_lower = command.lower().strip()
    # DHCP 配置已应用时，优先使用已配置状态的输出
    if _dhcp_config_applied:
        applied_outputs = _MOCK_OUTPUTS_DHCP_APPLIED.get(cmd_lower)
        if applied_outputs and device_name in applied_outputs:
            return applied_outputs[device_name]
    device_outputs = _MOCK_OUTPUTS.get(cmd_lower)
    if device_outputs and device_name in device_outputs:
        return device_outputs[device_name]
    return _DEFAULT_OUTPUT.format(command=command)


def build_devices_from_topology(topo: TopologyData) -> list[DeviceInfo]:
    """从拓扑数据构建设备信息列表（不含连接配置）。

    连接配置（host, port, protocol）需要从 devices.yaml 补充。
    """
    devices = []
    for topo_dev in topo.devices:
        devices.append(DeviceInfo(
            id=topo_dev.id,
            name=topo_dev.name,
            type=topo_dev.device_type,
            vendor=topo_dev.vendor,
            model=topo_dev.model,
        ))
    return devices


def load_connection_config() -> dict[str, dict]:
    """从 config/devices.yaml 加载连接配置，按设备名索引。"""
    config_path = get_devices_config_path()
    if not config_path.exists():
        return {}

    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    config_map = {}
    for item in data.get("devices", []):
        config_map[item["name"]] = {
            "host": item.get("host"),
            "port": item.get("port"),
            "protocol": item.get("protocol"),
            "username_env": item.get("username_env"),
            "password_env": item.get("password_env"),
        }
    return config_map


def merge_device_info(
    topo_devices: list[DeviceInfo],
    connection_config: dict[str, dict],
) -> list[DeviceInfo]:
    """将拓扑设备信息与连接配置合并。"""
    merged = []
    for dev in topo_devices:
        cfg = connection_config.get(dev.name, {})
        merged.append(DeviceInfo(
            id=dev.id,
            name=dev.name,
            type=dev.type,
            vendor=dev.vendor,
            model=dev.model,
            host=cfg.get("host"),
            port=cfg.get("port"),
            protocol=cfg.get("protocol"),
        ))
    return merged


class MockAdapter(BaseAdapter):
    """Mock 设备适配器。

    设备清单从外部注入（由 topology 解析结果构建），
    不再硬编码设备列表。
    """

    def __init__(self, devices: list[DeviceInfo]):
        self._devices = devices
        self._device_map = {d.id: d for d in devices}

    @staticmethod
    def _build_managed_config_commands(
        device_name: str,
        commands: list[str],
    ) -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()
        for command in [
            f"sysname {device_name}",
            "undo info-center enable",
            *commands,
        ]:
            normalized = command.strip()
            if not normalized or normalized in seen:
                continue
            merged.append(normalized)
            seen.add(normalized)
        return merged

    def list_devices(self) -> list[DeviceInfo]:
        """返回设备列表。"""
        return list(self._devices)

    def get_device_status(self, device_id: str) -> DeviceStatus:
        """返回模拟设备状态。"""
        device = self._device_map.get(device_id)
        if not device:
            raise DeviceNotFoundError(device_id)

        if device.type == "pc":
            raise DeviceConnectionError(
                device_id=device_id,
                reason=f"设备类型 {device.type} 不支持运行状态查询",
            )

        return DeviceStatus(
            device_id=device.id,
            device_name=device.name,
            is_online=True,
            uptime="1 day, 3 hours, 25 minutes",
            cpu_usage="5%",
            memory_usage="32%",
            version="V200R003C00SPC200",
            checked_at=datetime.now().isoformat(),
        )

    def run_show_command(self, device_id: str, command: str) -> CommandResult:
        """返回模拟命令执行结果。"""
        normalized = check_command(command)

        device = self._device_map.get(device_id)
        if not device:
            raise DeviceNotFoundError(device_id)

        if device.type == "pc":
            raise DeviceConnectionError(
                device_id=device_id,
                reason=f"设备类型 {device.type} 不支持命令执行",
            )

        output = _get_mock_output(device.name, normalized)

        return CommandResult(
            device_id=device.id,
            device_name=device.name,
            command=normalized,
            normalized_command=normalized,
            success=True,
            output=output,
            executed_at=datetime.now().isoformat(),
        )

    def backup_config(self, device_id: str) -> BackupResult:
        """返回模拟配置备份结果。"""
        device = self._device_map.get(device_id)
        if not device:
            raise DeviceNotFoundError(device_id)

        if device.type == "pc":
            raise DeviceConnectionError(
                device_id=device_id,
                reason=f"设备类型 {device.type} 不支持配置备份",
            )

        config_output = _get_mock_output(device.name, "display current-configuration")

        return BackupResult(
            device_id=device.id,
            device_name=device.name,
            success=True,
            backup_path=str(
                (
                    get_backups_dir()
                    / f"{device.name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.cfg"
                ).resolve()
            ),
            backed_up_at=datetime.now().isoformat(),
        )

    _DIAGNOSTIC_COMMANDS = [
        "display version",
        "display interface brief",
        "display ip interface brief",
        "display ip routing-table",
        "display ospf peer",
        "display ospf brief",
        "display vlan",
    ]

    _SWITCH_DIAGNOSTIC_COMMANDS = [
        "display version",
        "display interface brief",
        "display vlan",
        "display current-configuration",
        "display ip pool",
        "display dhcp statistics",
    ]

    def get_device_diagnostics(self, device_id: str) -> DeviceDiagnostics:
        """返回模拟诊断数据。"""
        device = self._device_map.get(device_id)
        if not device:
            raise DeviceNotFoundError(device_id)

        if device.type == "pc":
            raise DeviceConnectionError(
                device_id=device_id,
                reason=f"设备类型 {device.type} 不支持诊断查询",
            )

        # 根据设备类型选择诊断命令列表
        if device.type == "switch":
            diag_commands = self._SWITCH_DIAGNOSTIC_COMMANDS
        else:
            diag_commands = self._DIAGNOSTIC_COMMANDS

        commands: list[CommandOutput] = []
        for cmd in diag_commands:
            output = _get_mock_output(device.name, cmd)
            commands.append(CommandOutput(
                command=cmd,
                success=True,
                output=output,
            ))

        return DeviceDiagnostics(
            device_id=device.id,
            device_name=device.name,
            collected_at=datetime.now().isoformat(),
            commands=commands,
        )

    def run_config_commands(
        self, device_id: str, commands: list[str]
    ) -> list[ConfigCommandResult]:
        """返回模拟配置命令执行结果。"""
        device = self._device_map.get(device_id)
        if not device:
            raise DeviceNotFoundError(device_id)

        if device.type == "pc":
            raise DeviceConnectionError(
                device_id=device_id,
                reason=f"设备类型 {device.type} 不支持配置命令",
            )

        managed_commands = self._build_managed_config_commands(
            device.name,
            commands,
        )
        results: list[ConfigCommandResult] = []
        for cmd in managed_commands:
            results.append(ConfigCommandResult(
                command=cmd,
                success=True,
                output=f"[模拟] 已在 {device.name} 上执行: {cmd}",
            ))
        return results

    def save_config(self, device_id: str) -> SaveResult:
        """返回模拟配置保存结果。"""
        device = self._device_map.get(device_id)
        if not device:
            raise DeviceNotFoundError(device_id)

        if device.type == "pc":
            raise DeviceConnectionError(
                device_id=device_id,
                reason=f"设备类型 {device.type} 不支持配置保存",
            )

        save_output = (
            f"[mock] {device.name} save -> y"
            if device.type == "router"
            else f"[mock] {device.name} save {device.name}.zip -> y"
        )

        return SaveResult(
            device_id=device.id,
            device_name=device.name,
            success=True,
            output=save_output,
            saved_at=datetime.now().isoformat(),
        )

    def restore_config(self, device_id: str, backup_path: str) -> RestoreResult:
        """返回模拟配置恢复结果。"""
        device = self._device_map.get(device_id)
        if not device:
            raise DeviceNotFoundError(device_id)

        if device.type == "pc":
            raise DeviceConnectionError(
                device_id=device_id,
                reason=f"设备类型 {device.type} 不支持配置恢复",
            )

        return RestoreResult(
            device_id=device.id,
            device_name=device.name,
            success=True,
            output=f"[模拟] {device.name} 配置已从 {backup_path} 恢复",
            backup_path=backup_path,
            restored_at=datetime.now().isoformat(),
        )

    def get_pc_dhcp_status(self, pc_name: str) -> PcDhcpStatus:
        """返回 PC 的 DHCP 状态（受 _dhcp_config_applied 标志控制）。"""
        if pc_name not in _EXPECTED_PCS:
            return PcDhcpStatus(
                pc_name=pc_name,
                available=False,
                note=f"未知的 PC 设备: {pc_name}",
            )

        if _dhcp_config_applied:
            expected = _EXPECTED_PCS[pc_name]
            return PcDhcpStatus(
                pc_name=pc_name,
                ip_address=expected["ip"],  # type: ignore[index]
                mask=expected["mask"],  # type: ignore[index]
                gateway=expected["gateway"],  # type: ignore[index]
                dhcp_state=expected["dhcp_state"],  # type: ignore[index]
                available=True,
                note="Mock 模式：DHCP 配置已应用，PC 已获取地址",
            )

        return PcDhcpStatus(
            pc_name=pc_name,
            ip_address=None,
            mask=None,
            gateway=None,
            dhcp_state=0,
            available=True,
            note="Mock 模式：DHCP 配置未应用，PC 未获取地址",
        )
