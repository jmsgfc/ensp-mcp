import importlib

from fastapi.testclient import TestClient

from backend.runtime import context as runtime_context
from backend.services.log_service import LogService


class _FakeDeviceService:
    def __init__(self, refresh_error=None):
        self.refresh_calls = 0
        self.refresh_error = refresh_error

    def refresh_adapter(self):
        self.refresh_calls += 1
        if self.refresh_error is not None:
            raise self.refresh_error

    def list_devices(self):
        return []


def _load_main_module(monkeypatch, fake_service):
    monkeypatch.setattr(runtime_context, "get_device_service", lambda: fake_service)
    monkeypatch.setattr(runtime_context, "get_log_service", lambda: LogService())
    main = importlib.import_module("backend.main")
    return importlib.reload(main)


def test_api_refresh_middleware_refreshes_device_service_for_devices(monkeypatch):
    fake_service = _FakeDeviceService()
    main = _load_main_module(monkeypatch, fake_service)
    client = TestClient(main.app)

    response = client.get("/api/devices")

    assert response.status_code == 200
    assert fake_service.refresh_calls == 1


def test_api_refresh_middleware_skips_logs(monkeypatch):
    fake_service = _FakeDeviceService()
    main = _load_main_module(monkeypatch, fake_service)
    client = TestClient(main.app)

    response = client.get("/api/logs")

    assert response.status_code == 200
    assert fake_service.refresh_calls == 0


def test_api_refresh_middleware_returns_topology_unavailable(monkeypatch):
    fake_service = _FakeDeviceService(refresh_error=FileNotFoundError("no topo"))
    main = _load_main_module(monkeypatch, fake_service)
    client = TestClient(main.app)

    response = client.get("/api/devices")

    assert response.status_code == 409
    assert response.json()["error_code"] == "TOPOLOGY_UNAVAILABLE"
