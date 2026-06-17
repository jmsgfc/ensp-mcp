"""拓扑与 devices.yaml 一致性校验。

校验规则：
1. devices.yaml 中的设备必须在拓扑中存在
2. 同名设备的 ID 必须一致
3. 同名设备的端口（devices.yaml 的 port vs 拓扑的 com_port）必须一致
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from backend.topology.config import get_devices_config_path
from backend.topology.models import TopologyData


@dataclass
class ValidationError:
    """单条校验错误。"""
    device_name: str
    field: str
    expected: str
    actual: str
    message: str


@dataclass
class ValidationResult:
    """校验结果。"""
    is_valid: bool
    errors: list[ValidationError]

    def __str__(self) -> str:
        if self.is_valid:
            return "校验通过"
        lines = ["校验失败:"]
        for err in self.errors:
            lines.append(f"  - [{err.device_name}] {err.message}")
        return "\n".join(lines)


def load_devices_yaml(path: Optional[Path] = None) -> list[dict]:
    """加载 devices.yaml 配置。

    Args:
        path: devices.yaml 路径，默认为 config/devices.yaml
    """
    if path is None:
        path = get_devices_config_path()
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("devices", [])


def validate_devices_yaml_against_topology(
    topo: TopologyData,
    yaml_devices: Optional[list[dict]] = None,
    yaml_path: Optional[Path] = None,
) -> ValidationResult:
    """校验 devices.yaml 与拓扑数据的一致性。

    校验规则：
    1. devices.yaml 中存在但拓扑中不存在的设备 → 报错
    2. 同名设备 ID 不一致 → 报错
    3. 同名设备 port 与 com_port 不一致 → 报错

    Args:
        topo: 已解析的拓扑数据
        yaml_devices: devices.yaml 中的设备列表，为 None 时自动加载
        yaml_path: devices.yaml 路径，为 None 时使用默认路径

    Returns:
        ValidationResult
    """
    if yaml_devices is None:
        yaml_devices = load_devices_yaml(yaml_path)

    errors: list[ValidationError] = []

    # 按设备名索引拓扑设备
    topo_by_name = {d.name: d for d in topo.devices}

    for yaml_dev in yaml_devices:
        name = yaml_dev.get("name")
        if not name:
            continue

        topo_dev = topo_by_name.get(name)

        # 规则 1：devices.yaml 中存在但拓扑中不存在
        if topo_dev is None:
            errors.append(ValidationError(
                device_name=name,
                field="existence",
                expected="存在于拓扑中",
                actual="拓扑中未找到",
                message=f"设备 {name} 存在于 devices.yaml 但不在拓扑文件中",
            ))
            continue

        # 规则 2：同名设备 ID 不一致
        yaml_id = yaml_dev.get("id")
        if yaml_id and yaml_id != topo_dev.id:
            errors.append(ValidationError(
                device_name=name,
                field="id",
                expected=topo_dev.id,
                actual=yaml_id,
                message=f"设备 {name} 的 ID 不一致: devices.yaml={yaml_id}, 拓扑={topo_dev.id}",
            ))

        # 规则 3：同名设备 port 与 com_port 不一致
        yaml_port = yaml_dev.get("port")
        topo_com_port = topo_dev.com_port
        if yaml_port is not None and topo_com_port is not None:
            if yaml_port != topo_com_port:
                errors.append(ValidationError(
                    device_name=name,
                    field="port",
                    expected=str(topo_com_port),
                    actual=str(yaml_port),
                    message=f"设备 {name} 端口不一致: devices.yaml={yaml_port}, 拓扑 com_port={topo_com_port}",
                ))

    return ValidationResult(
        is_valid=len(errors) == 0,
        errors=errors,
    )
