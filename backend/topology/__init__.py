"""backend.topology 包公共导出。

其他模块应通过此包导入常用接口，而非直接依赖子模块内部路径。
"""

from backend.topology.config import get_topology_path
from backend.topology.models import (
    DeviceTopoInfo,
    InterfaceInfo,
    LinkInfo,
    TopologyData,
)
from backend.topology.parser import TopologyParseError, parse_topology
from backend.topology.validator import (
    load_devices_yaml,
    validate_devices_yaml_against_topology,
)

__all__ = [
    # 解析
    "parse_topology",
    "TopologyParseError",
    # 路径配置
    "get_topology_path",
    # 数据模型
    "TopologyData",
    "DeviceTopoInfo",
    "LinkInfo",
    "InterfaceInfo",
    # 校验
    "load_devices_yaml",
    "validate_devices_yaml_against_topology",
]
