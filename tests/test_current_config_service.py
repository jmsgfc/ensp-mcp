from backend.adapters.base_adapter import DeviceInfo
from backend.adapters.mock_adapter import MockAdapter
from backend.services.device_service import DeviceService
from backend.services.log_service import LogAction, LogService


def _make_service() -> DeviceService:
    service = DeviceService.__new__(DeviceService)
    service._log_service = LogService()
    service._adapter = MockAdapter(
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
                id="pc1-id",
                name="PC1",
                type="pc",
                vendor="virtual",
                model="PC",
            ),
        ]
    )
    return service


def test_get_device_current_config_returns_running_config_without_success_log():
    service = _make_service()

    result = service.get_device_current_config("ar1-id")

    assert result.device_name == "AR1"
    assert "sysname AR1" in result.output
    assert result.normalized_command == "display current-configuration"
    assert service._log_service.get_logs(action=LogAction.COMMAND_EXEC) == []
