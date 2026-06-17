"""拓扑数据模型。

从 .topo 文件解析出的设备、接口、链路的结构化表示。
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class InterfaceInfo:
    """设备接口信息。"""
    sztype: str          # 接口类型，如 "Ethernet"
    interfacename: str   # 接口名称前缀，如 "GE"、"Ethernet"
    count: int           # 接口编号


@dataclass
class DeviceTopoInfo:
    """从拓扑文件解析出的设备信息。"""
    id: str
    name: str
    model: str
    system_mac: str
    com_port: int
    cx: float = 0.0
    cy: float = 0.0
    poe: int = 0
    bootmode: int = 0
    interfaces: list[InterfaceInfo] = field(default_factory=list)

    @property
    def device_type(self) -> str:
        """根据 model 推断设备类型。"""
        if self.model.upper() == "PC":
            return "pc"
        if self.model.upper() in ("S5700", "S3700"):
            return "switch"
        return "router"

    @property
    def vendor(self) -> str:
        """根据 model 推断厂商。"""
        if self.model.upper() == "PC":
            return "virtual"
        return "huawei"


@dataclass
class LinkInfo:
    """设备间链路信息。"""
    src_device_id: str
    dest_device_id: str
    line_name: str
    src_index: int
    tar_index: int


@dataclass
class TopologyData:
    """完整拓扑数据。"""
    version: str
    devices: list[DeviceTopoInfo] = field(default_factory=list)
    links: list[LinkInfo] = field(default_factory=list)

    def get_device_by_id(self, device_id: str) -> Optional[DeviceTopoInfo]:
        """按 ID 查找设备。"""
        for d in self.devices:
            if d.id == device_id:
                return d
        return None

    def get_device_by_name(self, name: str) -> Optional[DeviceTopoInfo]:
        """按名称查找设备。"""
        for d in self.devices:
            if d.name == name:
                return d
        return None

    def get_links_for_device(self, device_id: str) -> list[LinkInfo]:
        """获取指定设备的所有链路。"""
        return [
            link for link in self.links
            if link.src_device_id == device_id or link.dest_device_id == device_id
        ]
