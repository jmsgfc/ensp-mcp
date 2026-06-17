import pytest

from backend.topology.interface_mapping import interface_name
from backend.topology.models import DeviceTopoInfo, InterfaceInfo


def _device(model, interfaces):
    return DeviceTopoInfo(
        id=model,
        name=model,
        model=model,
        system_mac="",
        com_port=0,
        interfaces=interfaces,
    )


def test_s5700_ge_index_starts_at_one():
    device = _device("S5700", [InterfaceInfo("GE", "GE", 24)])

    assert interface_name(device, 0) == "GigabitEthernet0/0/1"
    assert interface_name(device, 23) == "GigabitEthernet0/0/24"


def test_s3700_ethernet_index_starts_at_one():
    device = _device("S3700", [InterfaceInfo("Ethernet", "Ethernet", 24)])

    assert interface_name(device, 0) == "Ethernet0/0/1"
    assert interface_name(device, 5) == "Ethernet0/0/6"


def test_ar2220_ge_index_starts_at_zero():
    device = _device("AR2220", [InterfaceInfo("GE", "GE", 3)])

    assert interface_name(device, 0) == "GigabitEthernet0/0/0"
    assert interface_name(device, 2) == "GigabitEthernet0/0/2"


def test_interface_index_out_of_range_fails_loudly():
    device = _device("S5700", [InterfaceInfo("GE", "GE", 1)])

    with pytest.raises(ValueError):
        interface_name(device, 2)
