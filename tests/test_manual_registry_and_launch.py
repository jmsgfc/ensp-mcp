import importlib
from pathlib import Path

from backend.services import manual_device_registry as registry
from backend import launch


def test_manual_device_registry_round_trip(monkeypatch, tmp_path):
    monkeypatch.setattr(registry, "_OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(registry, "_REGISTRY_PATH", tmp_path / "registered_devices.json")

    created = registry.register_device("R1", "127.0.0.1", 2000)
    assert created["success"] is True
    assert created["device"]["name"] == "R1"

    listed = registry.list_registered_devices()
    assert len(listed) == 1
    assert listed[0]["port"] == 2000

    removed = registry.unregister_device("R1")
    assert removed["removed"] is True
    assert registry.list_registered_devices() == []


def test_auto_discover_devices_merges_results(monkeypatch, tmp_path):
    monkeypatch.setattr(registry, "_OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(registry, "_REGISTRY_PATH", tmp_path / "registered_devices.json")
    monkeypatch.setattr(registry, "_probe_port", lambda host, port, timeout=0.5: port in {2000, 2001})
    monkeypatch.setattr(registry, "_discover_device_name", lambda host, port: f"R{port - 1999}")

    result = registry.auto_discover_devices(start_port=2000, end_port=2002)

    assert result["success"] is True
    assert result["count"] == 2
    assert [item["name"] for item in result["devices"]] == ["R1", "R2"]
    assert len(registry.list_registered_devices()) == 2


def test_build_launch_env_prefers_explicit_topology(tmp_path):
    topo = tmp_path / "lab.topo"
    topo.write_text("topo", encoding="utf-8")

    env = launch._build_launch_env(str(topo), None, enable_real_ensp=True)

    assert env["TOPOLOGY_FILE"] == str(topo.resolve())
    assert env["ENSP_MCP_CALLER_CWD"] == str(topo.parent.resolve())
    assert env["ENABLE_REAL_ENSP"] == "true"


def test_build_launch_env_defaults_to_real_ensp():
    env = launch._build_launch_env()

    assert env["ENABLE_REAL_ENSP"] == "true"


def test_topology_start_hint_delegates_search(monkeypatch):
    monkeypatch.setattr(
        launch,
        "find_topology_files",
        lambda search_dir=None, max_results=5: {"success": True, "search_dir": search_dir, "count": 0},
    )

    result = launch._topology_start_hint(workspace_dir="C:/labs")

    assert result["success"] is True
    assert result["search_dir"] == "C:/labs"
