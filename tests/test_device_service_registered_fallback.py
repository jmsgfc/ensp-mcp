import backend.services.device_service as device_service_module
from backend.adapters.base_adapter import DeviceInfo
from backend.services.device_service import DeviceService
from backend.services.log_service import LogService


class DummyAdapter:
    def __init__(self, devices_config=None, enable_real=False):
        self._devices = [
            DeviceInfo(
                id=item["id"],
                name=item["name"],
                type=item["type"],
                vendor=item["vendor"],
                model=item["model"],
                host=item["host"],
                port=item["port"],
                protocol=item["protocol"],
            )
            for item in (devices_config or [])
        ]

    def list_devices(self):
        return list(self._devices)


def test_refresh_adapter_falls_back_to_registered_devices(monkeypatch):
    monkeypatch.setattr(device_service_module, "_create_adapter", lambda _log_service: DummyAdapter())
    service = DeviceService(log_service=LogService())

    monkeypatch.setattr(
        device_service_module,
        "_create_adapter",
        lambda _log_service: (_ for _ in ()).throw(FileNotFoundError("no topo")),
    )
    monkeypatch.setattr(device_service_module, "has_registered_devices", lambda: True)
    monkeypatch.setattr(
        device_service_module,
        "list_registered_devices",
        lambda: [{
            "id": "manual-1",
            "name": "R1",
            "type": "router",
            "vendor": "huawei",
            "model": "manual",
            "host": "127.0.0.1",
            "port": 2000,
            "protocol": "telnet",
        }],
    )
    monkeypatch.setattr(device_service_module, "ENSPAdapter", DummyAdapter)

    service.refresh_adapter(allow_registered_fallback=True)

    assert service.source_mode == "registered"
    assert service.list_devices()[0].name == "R1"
