import importlib

import pytest

import backend.topology.config as topology_config


def _reload_config_module():
    return importlib.reload(topology_config)


def test_get_topology_path_prefers_explicit_env(monkeypatch, tmp_path):
    topo_path = tmp_path / "custom.topo"
    devices_path = tmp_path / "custom-devices.yaml"
    topo_path.write_text("topo", encoding="utf-8")
    devices_path.write_text("devices: []", encoding="utf-8")

    monkeypatch.setenv("TOPOLOGY_FILE", str(topo_path))
    monkeypatch.setenv("DEVICES_FILE", str(devices_path))
    module = _reload_config_module()

    assert module.get_topology_path() == topo_path
    assert module.get_devices_config_path() == devices_path


def test_get_topology_path_resolves_relative_env_from_current_directory(monkeypatch, tmp_path):
    workspace_dir = tmp_path / "lab-c"
    workspace_dir.mkdir()
    topo_path = workspace_dir / "custom.topo"
    topo_path.write_text("topo", encoding="utf-8")

    monkeypatch.setenv("ENSP_MCP_CALLER_CWD", str(workspace_dir))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TOPOLOGY_FILE", "custom.topo")
    monkeypatch.delenv("DEVICES_FILE", raising=False)
    module = _reload_config_module()

    assert module.get_topology_path() == topo_path.resolve()


def test_get_topology_path_prefers_caller_cwd_before_process_cwd(monkeypatch, tmp_path):
    caller_workspace = tmp_path / "caller-lab"
    caller_workspace.mkdir()
    caller_topo = caller_workspace / "caller-lab.topo"
    caller_topo.write_text("topo", encoding="utf-8")

    process_workspace = tmp_path / "process-lab"
    process_workspace.mkdir()
    process_topo = process_workspace / "process-lab.topo"
    process_topo.write_text("topo", encoding="utf-8")

    monkeypatch.delenv("TOPOLOGY_FILE", raising=False)
    monkeypatch.delenv("DEVICES_FILE", raising=False)
    monkeypatch.setenv("ENSP_MCP_CALLER_CWD", str(caller_workspace))
    monkeypatch.chdir(process_workspace)
    module = _reload_config_module()

    assert module.get_topology_path() == caller_topo.resolve()
    assert module.get_topology_workspace_dir() == caller_workspace.resolve()
    assert module.get_topology_path() != process_topo.resolve()


def test_get_topology_path_ignores_legacy_workspace_fallback_envs(monkeypatch, tmp_path):
    caller_workspace = tmp_path / "caller-lab"
    caller_workspace.mkdir()
    caller_topo = caller_workspace / "caller-lab.topo"
    caller_topo.write_text("topo", encoding="utf-8")

    process_workspace = tmp_path / "process-lab"
    process_workspace.mkdir()
    process_topo = process_workspace / "process-lab.topo"
    process_topo.write_text("topo", encoding="utf-8")

    monkeypatch.delenv("TOPOLOGY_FILE", raising=False)
    monkeypatch.delenv("DEVICES_FILE", raising=False)
    monkeypatch.delenv("ENSP_MCP_CALLER_CWD", raising=False)
    monkeypatch.setenv("ENSP_MCP_WORKSPACE_DIR", str(caller_workspace))
    monkeypatch.setenv("CODEX_WORKSPACE", str(caller_workspace))
    monkeypatch.setenv("WORKSPACE", str(caller_workspace))
    monkeypatch.chdir(process_workspace)
    module = _reload_config_module()

    assert module.get_topology_path() == process_topo.resolve()
    assert module.get_topology_workspace_dir() == process_workspace.resolve()


def test_get_topology_path_uses_current_directory_named_topo(monkeypatch, tmp_path):
    workspace_dir = tmp_path / "work88"
    workspace_dir.mkdir()
    topo_path = workspace_dir / "work88.topo"
    topo_path.write_text("topo", encoding="utf-8")

    monkeypatch.delenv("TOPOLOGY_FILE", raising=False)
    monkeypatch.delenv("DEVICES_FILE", raising=False)
    monkeypatch.delenv("ENSP_MCP_CALLER_CWD", raising=False)
    monkeypatch.chdir(workspace_dir)
    module = _reload_config_module()

    assert module.get_topology_path() == topo_path.resolve()
    assert module.get_topology_workspace_dir() == workspace_dir.resolve()


def test_get_devices_config_path_follows_topology_workspace(monkeypatch, tmp_path):
    workspace_dir = tmp_path / "lab-a"
    config_dir = workspace_dir / "config"
    config_dir.mkdir(parents=True)
    topo_path = workspace_dir / "lab-a.topo"
    devices_path = config_dir / "devices.yaml"
    topo_path.write_text("topo", encoding="utf-8")
    devices_path.write_text("devices: []", encoding="utf-8")

    monkeypatch.delenv("TOPOLOGY_FILE", raising=False)
    monkeypatch.delenv("DEVICES_FILE", raising=False)
    monkeypatch.delenv("ENSP_MCP_CALLER_CWD", raising=False)
    monkeypatch.chdir(workspace_dir)
    module = _reload_config_module()

    assert module.get_devices_config_path() == devices_path



def test_get_devices_config_path_falls_back_to_project_default_for_current_topo(monkeypatch, tmp_path):
    workspace_dir = tmp_path / "lab-b"
    workspace_dir.mkdir()
    topo_path = workspace_dir / "lab-b.topo"
    topo_path.write_text("topo", encoding="utf-8")

    monkeypatch.delenv("TOPOLOGY_FILE", raising=False)
    monkeypatch.delenv("DEVICES_FILE", raising=False)
    monkeypatch.delenv("ENSP_MCP_CALLER_CWD", raising=False)
    monkeypatch.chdir(workspace_dir)
    module = _reload_config_module()

    assert module.get_topology_path() == topo_path.resolve()
    assert module.get_devices_config_path() == module._DEFAULT_DEVICES


def test_get_topology_path_raises_when_current_directory_has_no_topology(monkeypatch, tmp_path):
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    monkeypatch.delenv("TOPOLOGY_FILE", raising=False)
    monkeypatch.delenv("DEVICES_FILE", raising=False)
    monkeypatch.delenv("ENSP_MCP_WORKSPACE_DIR", raising=False)
    monkeypatch.delenv("ENSP_MCP_CALLER_CWD", raising=False)
    monkeypatch.delenv("CODEX_WORKSPACE", raising=False)
    monkeypatch.delenv("WORKSPACE", raising=False)
    monkeypatch.chdir(empty_dir)
    module = _reload_config_module()

    with pytest.raises(FileNotFoundError):
        module.get_topology_path()
