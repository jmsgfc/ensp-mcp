import importlib
from types import SimpleNamespace

from backend.adapters.base_adapter import DeviceInfo
from backend.adapters.mock_adapter import MockAdapter
from backend.runtime import context as runtime_context
from backend.services import config_deploy_service
from backend.services.config_deploy_service import FinalSuccessCheck, save_all_configs
from backend.services.log_service import LogService


def _make_adapter() -> MockAdapter:
    return MockAdapter(
        devices=[
            DeviceInfo(
                id="ar1-id",
                name="AR1",
                type="router",
                vendor="huawei",
                model="AR2220",
                host="127.0.0.1",
                port=2000,
                protocol="telnet",
            ),
            DeviceInfo(
                id="lsw1-id",
                name="LSW1",
                type="switch",
                vendor="huawei",
                model="S5700",
                host="127.0.0.1",
                port=2001,
                protocol="telnet",
            ),
            DeviceInfo(
                id="pc1-id",
                name="PC1",
                type="pc",
                vendor="virtual",
                model="PC",
            ),
        ]
    )


def _load_tools_module(monkeypatch, adapter):
    monkeypatch.setattr(runtime_context, "get_device_service", lambda: SimpleNamespace(adapter=adapter))
    monkeypatch.setattr(runtime_context, "get_log_service", lambda: LogService())
    tools = importlib.import_module("backend.mcp.tools")
    return importlib.reload(tools)


def test_save_all_configs_saves_router_and_switch_only():
    result = save_all_configs(
        adapter=_make_adapter(),
        log_service=LogService(),
    )

    assert result.success is True
    assert [item.device_name for item in result.device_results] == ["AR1", "LSW1"]
    outputs = {item.device_name: item.output for item in result.device_results}
    assert outputs["AR1"] == "[mock] AR1 save -> y"
    assert outputs["LSW1"] == "[mock] LSW1 save LSW1.zip -> y"


def test_preview_save_returns_grouped_router_and_switch_targets(monkeypatch):
    adapter = _make_adapter()
    service = SimpleNamespace(adapter=adapter)
    tools = _load_tools_module(monkeypatch, adapter)

    monkeypatch.setattr(
        config_deploy_service,
        "check_final_success",
        lambda _adapter: FinalSuccessCheck(
            is_success=True,
            health_ready=True,
            both_reachable=True,
            deploy_ok=True,
        ),
    )

    preview = tools._handle_preview_save(service)

    assert preview == {
        "success": True,
        "devices": ["AR1", "LSW1"],
        "routers": ["AR1"],
        "switches": ["LSW1"],
    }


def test_preview_save_returns_no_targets_when_prerequisites_fail(monkeypatch):
    adapter = _make_adapter()
    service = SimpleNamespace(adapter=adapter)
    tools = _load_tools_module(monkeypatch, adapter)

    monkeypatch.setattr(
        config_deploy_service,
        "check_final_success",
        lambda _adapter: FinalSuccessCheck(
            is_success=False,
            health_ready=True,
            both_reachable=False,
            deploy_ok=True,
            reason="pc connectivity not ready",
        ),
    )

    preview = tools._handle_preview_save(service)

    assert preview == {
        "success": True,
        "devices": None,
        "routers": None,
        "switches": None,
        "message": "前置条件不满足，无法执行 save：pc connectivity not ready",
    }
