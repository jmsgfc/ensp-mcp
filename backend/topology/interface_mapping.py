"""Map eNSP topology interface indexes to Huawei VRP interface names."""

from __future__ import annotations

from backend.topology.models import DeviceTopoInfo


def _is_switch(device: DeviceTopoInfo) -> bool:
    model = device.model.upper()
    return device.device_type == "switch" or model.startswith("S")


def interface_name(device: DeviceTopoInfo, index: int) -> str:
    """Convert a topology interface index to a VRP interface name.

    eNSP stores link endpoints as zero-based indexes over the interface groups
    declared on each device. Switch GE/Ethernet labels in the UI start at 1
    (GE0/0/1), while AR router GE labels start at 0 (GE0/0/0).
    """

    if index < 0:
        raise ValueError(f"invalid negative interface index: {index}")

    remaining = index
    for iface in device.interfaces:
        if remaining >= iface.count:
            remaining -= iface.count
            continue

        base = iface.interfacename.strip()
        normalized = base.upper()
        if normalized == "GE":
            port = remaining + 1 if _is_switch(device) else index
            return f"GigabitEthernet0/0/{port}"
        if normalized == "ETHERNET":
            return f"Ethernet0/0/{remaining + 1}"
        if not base:
            raise ValueError(
                f"device {device.name} has empty interface name for index {index}"
            )
        return f"{base}0/0/{remaining}"

    raise ValueError(
        f"interface index {index} is out of range for {device.name} ({device.model})"
    )
