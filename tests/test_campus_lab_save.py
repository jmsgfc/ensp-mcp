from backend.services import campus_lab_service


def test_execute_campus_lab_saves_by_default_after_apply_and_verify(monkeypatch):
    calls = []

    monkeypatch.setattr(campus_lab_service, "plan_campus_lab", lambda: {"success": True})
    monkeypatch.setattr(campus_lab_service, "apply_campus_lab", lambda: {"success": True})
    monkeypatch.setattr(campus_lab_service, "verify_campus_lab", lambda: {"success": True})

    def fake_save():
        calls.append("save")
        return {"success": True, "results": {}}

    monkeypatch.setattr(campus_lab_service, "save_campus_lab", fake_save)

    result = campus_lab_service.execute_campus_lab(confirmed=True)

    assert result["success"] is True
    assert result["save"]["success"] is True
    assert calls == ["save"]


def test_execute_campus_lab_verify_can_save_after_success(monkeypatch):
    calls = []

    monkeypatch.setattr(campus_lab_service, "plan_campus_lab", lambda: {"success": True})
    monkeypatch.setattr(campus_lab_service, "verify_campus_lab", lambda: {"success": True, "summary": {}})

    def fake_save():
        calls.append("save")
        return {"success": True, "results": {}}

    monkeypatch.setattr(campus_lab_service, "save_campus_lab", fake_save)

    result = campus_lab_service.execute_campus_lab(mode="verify", save_on_success=True)

    assert result["success"] is True
    assert result["save"]["success"] is True
    assert calls == ["save"]


def test_execute_campus_lab_does_not_save_failed_verify(monkeypatch):
    calls = []

    monkeypatch.setattr(campus_lab_service, "plan_campus_lab", lambda: {"success": True})
    monkeypatch.setattr(campus_lab_service, "verify_campus_lab", lambda: {"success": False})
    monkeypatch.setattr(campus_lab_service, "save_campus_lab", lambda: calls.append("save"))

    result = campus_lab_service.execute_campus_lab(mode="verify", save_on_success=True)

    assert result["success"] is False
    assert "save" not in result
    assert calls == []
