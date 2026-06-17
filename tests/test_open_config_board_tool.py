import importlib
from types import SimpleNamespace

from backend.runtime import context as runtime_context
from backend.services.log_service import LogService


def _load_tools_module(monkeypatch, device_service=None):
    fake_service = device_service or SimpleNamespace(
        refresh_adapter=lambda: None,
        list_devices=lambda: [],
    )
    monkeypatch.setattr(runtime_context, "get_device_service", lambda: fake_service)
    monkeypatch.setattr(runtime_context, "get_log_service", lambda: LogService())
    tools = importlib.import_module("backend.mcp.tools")
    return importlib.reload(tools)


def test_open_config_board_supports_none_mode(monkeypatch):
    tools = _load_tools_module(monkeypatch)
    monkeypatch.setattr(
        tools,
        "_ensure_board_server",
        lambda **kwargs: {
            "success": True,
            "url": "http://127.0.0.1:8000/static/index.html",
            "host": "127.0.0.1",
            "port": 8000,
            "path": "/static/index.html",
            "server_started": False,
            "reachable": True,
        },
    )

    result = tools._handle_open_config_board(open_mode="none")

    assert result["success"] is True
    assert result["open_mode"] == "none"
    assert result["opened"] is False
    assert result["url"] == "http://127.0.0.1:8000/static/index.html"


def test_tools_import_and_list_tools_do_not_require_topology(monkeypatch):
    def fail_if_loaded():
        raise FileNotFoundError("no topo")

    monkeypatch.setattr(runtime_context, "get_device_service", fail_if_loaded)
    monkeypatch.setattr(runtime_context, "get_log_service", lambda: LogService())
    tools = importlib.import_module("backend.mcp.tools")
    tools = importlib.reload(tools)

    names = {tool["name"] for tool in tools.list_tools()}

    assert "list_devices" in names
    assert "open_config_board" in names


def test_topology_dependent_tool_returns_structured_topology_error(monkeypatch):
    class MissingTopologyService:
        def refresh_adapter(self):
            raise FileNotFoundError("no topo")

    tools = _load_tools_module(monkeypatch, device_service=MissingTopologyService())

    result = tools.call_tool("list_devices")

    assert result["success"] is False
    assert result["error_code"] == "TOPOLOGY_UNAVAILABLE"


def test_open_config_board_uses_editor_launcher(monkeypatch):
    tools = _load_tools_module(monkeypatch)
    monkeypatch.setattr(
        tools,
        "_ensure_board_server",
        lambda **kwargs: {
            "success": True,
            "url": "http://127.0.0.1:8000/static/index.html",
            "host": "127.0.0.1",
            "port": 8000,
            "path": "/static/index.html",
            "server_started": False,
            "reachable": True,
        },
    )
    monkeypatch.setattr(
        tools,
        "_open_board_in_editor",
        lambda url, editor_command=None: {
            "success": True,
            "open_mode": "editor",
            "editor_command": ["code"],
            "message": "ok",
        },
    )

    result = tools._handle_open_config_board(open_mode="editor", editor_command="code")

    assert result["success"] is True
    assert result["open_mode"] == "editor"
    assert result["opened"] is True
    assert result["launcher"]["editor_command"] == ["code"]


def test_open_config_board_rejects_unknown_mode(monkeypatch):
    tools = _load_tools_module(monkeypatch)

    result = tools._handle_open_config_board(open_mode="unsupported")

    assert result["success"] is False
    assert "不支持的打开模式" in result["error"]


def test_call_tool_auto_opens_board_once(monkeypatch):
    fake_service = SimpleNamespace(
        refresh_adapter=lambda: None,
        list_devices=lambda: [],
    )
    tools = _load_tools_module(monkeypatch, device_service=fake_service)
    monkeypatch.setenv("ENSP_MCP_AUTO_OPEN_BOARD", "true")
    monkeypatch.setattr(
        tools,
        "_handle_open_config_board",
        lambda open_mode="browser", editor_command=None, **_kwargs: {
            "success": True,
            "url": "http://127.0.0.1:8000/static/index.html",
            "open_mode": open_mode,
        },
    )
    monkeypatch.setattr(tools, "_is_url_available", lambda _url: True)
    tools._AUTO_BOARD_OPEN_ATTEMPTED = False
    tools._AUTO_BOARD_OPEN_URL = None

    first = tools.call_tool("list_devices")
    second = tools.call_tool("list_devices")

    assert first["config_board"]["success"] is True
    assert second["config_board"]["already_opened"] is True


def test_resolve_editor_command_prefers_cli_wrapper_for_app_exe(monkeypatch, tmp_path):
    tools = _load_tools_module(monkeypatch)
    app_dir = tmp_path / "Microsoft VS Code"
    app_dir.mkdir()
    exe_path = app_dir / "Code.exe"
    exe_path.write_text("", encoding="utf-8")
    bin_dir = app_dir / "bin"
    bin_dir.mkdir()
    cli_path = bin_dir / "code.cmd"
    cli_path.write_text("", encoding="utf-8")

    resolved = tools._resolve_editor_command(str(exe_path))

    assert resolved == [str(cli_path)]


def test_editor_open_commands_prefer_vscode_simple_browser(monkeypatch):
    tools = _load_tools_module(monkeypatch)

    commands = tools._build_editor_open_commands(
        ["code.cmd"],
        "http://127.0.0.1:8000/static/index.html",
    )

    assert commands[0][0:2] == ["code.cmd", "--open-url"]
    assert commands[0][2].startswith("vscode://command/simpleBrowser.show?")
    assert "http%3A%2F%2F127.0.0.1%3A8000%2Fstatic%2Findex.html" in commands[0][2]
    assert commands[1] == ["code.cmd", "--open-url", "http://127.0.0.1:8000/static/index.html"]


def test_editor_open_commands_support_cursor_simple_browser(monkeypatch):
    tools = _load_tools_module(monkeypatch)

    commands = tools._build_editor_open_commands(
        ["cursor.cmd"],
        "http://127.0.0.1:8000/static/index.html",
    )

    assert commands[0][0:2] == ["cursor.cmd", "--open-url"]
    assert commands[0][2].startswith("cursor://command/simpleBrowser.show?")
    assert commands[1] == ["cursor.cmd", "--open-url", "http://127.0.0.1:8000/static/index.html"]


def test_open_board_in_editor_falls_back_after_simple_browser_failure(monkeypatch):
    tools = _load_tools_module(monkeypatch)
    calls = []

    class Completed:
        def __init__(self, returncode, stderr=""):
            self.returncode = returncode
            self.stdout = ""
            self.stderr = stderr

    def fake_run(command, **kwargs):
        calls.append(command)
        if len(calls) == 1:
            return Completed(1, "command uri failed")
        return Completed(0)

    monkeypatch.setattr(tools, "_resolve_editor_command", lambda editor_command=None: ["code.cmd"])
    monkeypatch.setattr(tools.subprocess, "run", fake_run)

    result = tools._open_board_in_editor("http://127.0.0.1:8000/static/index.html")

    assert result["success"] is True
    assert result["command"] == ["code.cmd", "--open-url", "http://127.0.0.1:8000/static/index.html"]
    assert calls[0][2].startswith("vscode://command/simpleBrowser.show?")
