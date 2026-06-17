from unittest.mock import MagicMock, call

from backend.adapters.telnet_client import TelnetClient, TelnetConfig


def _make_client() -> TelnetClient:
    client = TelnetClient(TelnetConfig(host="127.0.0.1", port=23))
    client._tn = MagicMock()
    client._prompt = "<Huawei>"
    return client


def test_router_save_uses_save_then_y_then_enter(monkeypatch):
    client = _make_client()
    monkeypatch.setattr("backend.adapters.telnet_client.time.sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        client,
        "_read_save_until_confirm_or_prompt",
        lambda save_command, timeout: ("Are you sure to save? [Y/N]:", True),
    )
    monkeypatch.setattr(
        client,
        "_read_save_until_prompt",
        lambda *args, **kwargs: "\r\nWrite operation complete.\r\n<Huawei>",
    )

    output = client.send_save_command("router", "AR1", timeout=5.0)

    assert client._tn.write.call_args_list == [
        call(b"save\r"),
        call(b"y"),
        call(b"\r"),
    ]
    assert "Write operation complete." in output


def test_switch_save_uses_default_save_file(monkeypatch):
    client = _make_client()
    monkeypatch.setattr("backend.adapters.telnet_client.time.sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        client,
        "_read_save_until_confirm_or_prompt",
        lambda save_command, timeout: (
            "Info: Please input the file name (*.cfg, *.zip) [vrpcfg.zip]:",
            True,
        ),
    )
    monkeypatch.setattr(
        client,
        "_read_save_until_prompt",
        lambda *args, **kwargs: "\r\nWrite operation complete.\r\n<Huawei>",
    )

    output = client.send_save_command("switch", "LSW1", timeout=5.0)

    assert client._tn.write.call_args_list == [
        call(b"save\r"),
        call(b"y"),
        call(b"\r"),
    ]
    assert "Write operation complete." in output


def test_switch_save_confirms_overwrite_prompt(monkeypatch):
    class FakeTelnet:
        def __init__(self):
            self.writes = []
            self.reads = 0

        def read_very_eager(self):
            self.reads += 1
            if self.reads == 1:
                return b""
            if self.reads == 2:
                return b"Are you sure to save? [Y/N]:"
            if self.reads == 3:
                return b"\r\n<Huawei>\r\n"
            if self.reads == 4:
                return b"Info: Please input the file name ( *.cfg, *.zip ) [vrpcfg.zip]:"
            if self.reads == 5:
                return b"Overwrite the configuration file flash:/vrpcfg.zip? [Y/N]:"
            if self.reads == 6:
                return b"\r\nSave the configuration successfully.\r\n<Huawei>\r\n"
            return b""

        def write(self, data):
            self.writes.append(data)

    client = TelnetClient(TelnetConfig(host="127.0.0.1", port=23))
    client._tn = FakeTelnet()
    client._prompt = "<Huawei>"
    monkeypatch.setattr("backend.adapters.telnet_client.time.sleep", lambda *_args, **_kwargs: None)

    output = client.send_save_command("switch", "LSW1", timeout=5.0)

    assert client._tn.writes == [
        b"save\r",
        b"y",
        b"\r",
        b"\r",
        b"y",
        b"\r",
    ]
    assert "successfully" in output.lower()


def test_version_banner_is_not_treated_as_prompt():
    prompt = TelnetClient._extract_prompt_at_end(
        "display current-configuration\r\n[V200R003C00]\r\n",
        expected_prompt="<AR1>",
    )
    assert prompt is None


def test_send_command_keeps_reading_past_version_banner(monkeypatch):
    class FakeTelnet:
        def __init__(self):
            self.writes = []
            self.chunks = [
                b"\r\ndisplay current-configuration\r\n",
                b"[V200R003C00]\r\n#\r\n sysname AR1\r\n",
                b"<AR1>\r\n",
            ]

        def read_very_eager(self):
            if self.chunks:
                return self.chunks.pop(0)
            return b""

        def write(self, data):
            self.writes.append(data)

    client = TelnetClient(TelnetConfig(host="127.0.0.1", port=23))
    client._tn = FakeTelnet()
    client._prompt = "<AR1>"
    monkeypatch.setattr("backend.adapters.telnet_client.time.sleep", lambda *_args, **_kwargs: None)

    output = client.send_command("display current-configuration", timeout=5.0)

    assert "sysname AR1" in output
    assert client._prompt == "<AR1>"


def test_more_prompt_uses_space_not_q(monkeypatch):
    class FakeTelnet:
        def __init__(self):
            self.writes = []
            self.eager_reads = 0
            self.chunks = [
                b"display current-configuration\r\n line 1\r\n---- More ----",
                b"\r\n line 2\r\n<Huawei>\r\n",
            ]

        def read_very_eager(self):
            self.eager_reads += 1
            if self.eager_reads == 1:
                return b""
            if self.chunks:
                return self.chunks.pop(0)
            return b""

        def write(self, data):
            self.writes.append(data)

    client = TelnetClient(TelnetConfig(host="127.0.0.1", port=23))
    client._tn = FakeTelnet()
    client._prompt = "<Huawei>"
    monkeypatch.setattr("backend.adapters.telnet_client.time.sleep", lambda *_args, **_kwargs: None)

    output = client.send_command("display current-configuration", timeout=5.0)

    assert "line 2" in output
    assert b" " in client._tn.writes
    assert all(not write.startswith(b"q") for write in client._tn.writes)
