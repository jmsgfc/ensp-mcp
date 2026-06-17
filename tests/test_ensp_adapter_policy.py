from unittest.mock import MagicMock, call

from backend.adapters.ensp_adapter import ENSPAdapter


def _make_adapter() -> ENSPAdapter:
    return ENSPAdapter(
        devices_config=[
            {
                "id": "router-1",
                "name": "AR1",
                "type": "router",
                "vendor": "huawei",
                "model": "AR2220",
                "host": "127.0.0.1",
                "port": 2000,
                "protocol": "telnet",
                "username_env": "ENSP_R1_USERNAME",
                "password_env": "ENSP_R1_PASSWORD",
            }
        ],
        enable_real=True,
    )


def test_run_config_commands_injects_sysname_and_disables_info_center(monkeypatch):
    adapter = _make_adapter()
    client = MagicMock()
    disconnect = MagicMock()

    monkeypatch.setattr(adapter, "_open_fresh_client", lambda device_id, timeout=None: client)
    monkeypatch.setattr(adapter, "_prepare_user_view", lambda telnet_client: None)
    monkeypatch.setattr(adapter, "disconnect", disconnect)

    client.send_command.return_value = "ok"

    results = adapter.run_config_commands(
        "router-1",
        [
            "sysname AR1",
            "undo info-center enable",
            "interface LoopBack0",
            "ip address 1.1.1.1 255.255.255.255",
        ],
    )

    assert client.send_command.call_args_list == [
        call("system-view", timeout=20.0),
        call("sysname AR1", timeout=30.0),
        call("undo info-center enable", timeout=30.0),
        call("interface LoopBack0", timeout=30.0),
        call("ip address 1.1.1.1 255.255.255.255", timeout=30.0),
        call("return", timeout=10.0),
    ]
    assert [result.command for result in results] == [
        "sysname AR1",
        "undo info-center enable",
        "interface LoopBack0",
        "ip address 1.1.1.1 255.255.255.255",
    ]
    disconnect.assert_called_once_with("router-1")


def test_save_config_passes_device_type_and_name_to_telnet_save(monkeypatch):
    adapter = _make_adapter()
    client = MagicMock()
    disconnect = MagicMock()

    monkeypatch.setattr(adapter, "_open_fresh_client", lambda device_id, timeout=None: client)
    monkeypatch.setattr(adapter, "_prepare_user_view", lambda telnet_client: None)
    monkeypatch.setattr(adapter, "disconnect", disconnect)

    client.send_save_command.return_value = "saved"

    result = adapter.save_config("router-1")

    client.send_save_command.assert_called_once_with(
        device_type="router",
        device_name="AR1",
        timeout=20.0,
    )
    assert result.success is True
    assert result.output == "saved"
    disconnect.assert_called_once_with("router-1")

