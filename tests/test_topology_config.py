import importlib
from pathlib import Path

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

    monkeypatch.chdir(workspace_dir)
    monkeypatch.setenv("TOPOLOGY_FILE", "custom.topo")
    monkeypatch.delenv("DEVICES_FILE", raising=False)
    module = _reload_config_module()

    assert module.get_topology_path() == topo_path.resolve()


def test_get_topology_path_uses_current_directory_named_topo(monkeypatch, tmp_path):
    workspace_dir = tmp_path / "work88"
    workspace_dir.mkdir()
    topo_path = workspace_dir / "work88.topo"
    topo_path.write_text("topo", encoding="utf-8")

    monkeypatch.delenv("TOPOLOGY_FILE", raising=False)
    monkeypatch.delenv("DEVICES_FILE", raising=False)
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
    monkeypatch.chdir(workspace_dir)
    module = _reload_config_module()

    assert module.get_topology_path() == topo_path.resolve()
    assert module.get_devices_config_path() == module._DEFAULT_DEVICES


def test_get_topology_path_does_not_use_project_default(monkeypatch):
    monkeypatch.delenv("TOPOLOGY_FILE", raising=False)
    monkeypatch.delenv("DEVICES_FILE", raising=False)
    module = _reload_config_module()
    monkeypatch.chdir(module._PROJECT_ROOT)

    with pytest.raises(FileNotFoundError):
        module.get_topology_path()
