from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier, Thread
from uuid import uuid4

from fastapi.testclient import TestClient

from pinky_control_center.main import create_app
from pinky_control_center.models import UserRole

ORIGIN = "http://localhost:5173"


def login(client: TestClient, username: str, password: str) -> dict[str, str]:
    response = client.post("/api/v1/session", json={"username": username, "password": password}, headers={"origin": ORIGIN})
    assert response.status_code == 200
    return {"origin": ORIGIN, "x-csrf-token": response.json()["csrf_token"]}


def lease(client: TestClient, headers: dict[str, str]) -> dict[str, str]:
    value = client.post("/api/v1/control-lease", json={"request_id": str(uuid4())}, headers=headers)
    assert value.status_code == 200
    return {**headers, "x-control-lease-id": value.json()["lease_id"]}


def test_history_records_command_lifecycle_and_owner_scopes_results(tmp_path: Path) -> None:
    app = create_app(database_path=tmp_path / "control.db", start_command_worker=False)
    with TestClient(app) as client:
        app.state.storage.create_or_reset_user("operator", "operator-password", UserRole.OPERATOR)
        app.state.storage.create_or_reset_user("other", "other-password", UserRole.OPERATOR)
        headers = lease(client, login(client, "operator", "operator-password"))
        command = client.post("/api/v1/stop", json={"request_id": str(uuid4()), "target": "robot_1"}, headers=headers)
        assert command.status_code == 202
        asyncio.run(app.state.command_dispatcher.process_next())

        page = client.get("/api/v1/history?event_type=COMMAND_ACCEPTED")
        assert page.status_code == 200
        assert len(page.json()["items"]) == 1
        assert page.json()["items"][0]["robot_id"] == "robot_1"
        assert any(item["event_type"] == "COMMAND_RUNNING" for item in client.get("/api/v1/history").json()["items"])

        other = login(client, "other", "other-password")
        assert client.get("/api/v1/history", headers=other).json()["items"] == []


def test_history_filters_exports_and_keeps_alert_transitions(tmp_path: Path) -> None:
    now = [datetime(2026, 9, 11, tzinfo=UTC)]
    app = create_app(database_path=tmp_path / "control.db", start_command_worker=False, storage_clock=lambda: now[0])
    with TestClient(app) as client:
        app.state.storage.create_or_reset_user("operator", "operator-password", UserRole.OPERATOR)
        headers = login(client, "operator", "operator-password")
        app.state.storage.record_history_safe(event_type="ALERT_ACTIVE", robot_id="robot_2", payload={"code": "TF_INVALID"}, dedupe_key="alert:TF_INVALID:robot_2:ACTIVE")
        app.state.storage.record_history_safe(event_type="ALERT_ACK", robot_id="robot_2", payload={"code": "TF_INVALID"}, dedupe_key="alert:TF_INVALID:robot_2:ACK:one")
        app.state.storage.record_history_safe(event_type="ALERT_RESOLVED", robot_id="robot_2", payload={"code": "TF_INVALID"}, dedupe_key="alert:TF_INVALID:robot_2:RESOLVED:one")
        page = client.get("/api/v1/history?event_type=ALERT_ACTIVE&robot_id=robot_2&limit=1", headers=headers)
        assert page.status_code == 200
        assert page.json()["items"][0]["payload"]["code"] == "TF_INVALID"
        exported = client.get("/api/v1/history/export?robot_id=robot_2", headers=headers)
        assert exported.status_code == 200
        assert exported.headers["content-type"].startswith("application/json")
        assert [item["event_type"] for item in exported.json()["items"]] == ["ALERT_RESOLVED", "ALERT_ACK", "ALERT_ACTIVE"]
        too_wide = client.get(f"/api/v1/history?from={(now[0] - timedelta(days=32)).isoformat()}&to={now[0].isoformat()}", headers=headers)
        assert too_wide.status_code == 422


def test_audit_write_failure_is_degraded_without_blocking_protective_stop(tmp_path: Path, monkeypatch) -> None:
    app = create_app(database_path=tmp_path / "control.db", start_command_worker=False)
    with TestClient(app):
        monkeypatch.setattr(app.state.storage, "record_history_safe", lambda **_kwargs: False)
        calls = []
        original = app.state.adapter.execute
        async def execute(command):
            calls.append((command.robot_id, command.operation))
            return await original(command)
        monkeypatch.setattr(app.state.adapter, "execute", execute)
        asyncio.run(app.state.protective_stop("robot_1"))
        # The adapter still receives its pair-wide safety stop despite disabled audit storage.
        assert calls == [("robot_1", "stop"), ("robot_2", "stop")]


def test_main_sqlite_connection_serializes_watchdog_expiry_and_command_updates(tmp_path: Path) -> None:
    app = create_app(database_path=tmp_path / "control.db", start_command_worker=False)
    user = app.state.storage.create_or_reset_user("operator", "operator-password", UserRole.OPERATOR)
    command = app.state.storage.create_command(user, uuid4(), "robot_1", {"operation": "stop"})
    gate, errors = Barrier(2), []

    def expire() -> None:
        gate.wait()
        try:
            for _ in range(40): app.state.storage.expire_security()
        except Exception as error: errors.append(error)

    def transition() -> None:
        gate.wait()
        try:
            for _ in range(40): app.state.storage.set_command_state(str(command["command_id"]), "RUNNING")
        except Exception as error: errors.append(error)

    first, second = Thread(target=expire), Thread(target=transition)
    first.start(); second.start(); first.join(); second.join()
    assert errors == []
