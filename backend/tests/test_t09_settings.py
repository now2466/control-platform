from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from pinky_control_center.main import create_app
from pinky_control_center.models import MockScenario, RobotMode, UserRole

ORIGIN = "http://localhost:5173"


def _login(client: TestClient, name: str, password: str) -> dict[str, str]:
    response = client.post("/api/v1/session", json={"username": name, "password": password}, headers={"origin": ORIGIN})
    assert response.status_code == 200
    return {"origin": ORIGIN, "x-csrf-token": response.json()["csrf_token"]}


def _payload(version: int = 1, **changes: object) -> dict[str, object]:
    return {
        "request_id": str(uuid4()), "version": version, "active_map_id": "mock_lab_b",
        "follow_distance_m": 0.9, "follow_tolerance_m": 0.2,
        "max_linear_mps": 0.15, "max_angular_rps": 0.5, "camera_quality": "high", **changes,
    }


def test_settings_are_admin_only_versioned_bounded_and_persist_the_active_map(tmp_path: Path) -> None:
    path = tmp_path / "control.db"
    app = create_app(database_path=path, start_command_worker=False)
    with TestClient(app) as client:
        app.state.storage.create_or_reset_user("admin", "admin-password", UserRole.ADMIN)
        app.state.storage.create_or_reset_user("viewer", "viewer-password", UserRole.VIEWER)
        viewer = _login(client, "viewer", "viewer-password")
        assert client.get("/api/v1/settings").json()["active_map_id"] == "mock_lab"
        assert client.put("/api/v1/settings", json=_payload(), headers=viewer).status_code == 403
        assert client.post("/api/v1/robots/robot_1/initial-pose", json={"request_id": str(uuid4()), "pose": {"x": 1, "y": 1, "yaw": 0, "frame_id": "map"}}, headers=viewer).status_code == 403
        admin = _login(client, "admin", "admin-password")
        changed = client.put("/api/v1/settings", json=_payload(), headers=admin)
        assert changed.status_code == 200
        assert changed.json() == {"version": 2, "active_map_id": "mock_lab_b", "follow_distance_m": 0.9, "follow_tolerance_m": 0.2, "max_linear_mps": 0.15, "max_angular_rps": 0.5, "camera_quality": "high"}
        assert client.get("/api/v1/state").json()["map_id"] == "mock_lab_b"
        assert client.put("/api/v1/settings", json=_payload(version=1), headers=admin).status_code == 409
        assert client.put("/api/v1/settings", json=_payload(version=2, follow_tolerance_m=0.01), headers=admin).status_code == 422
    restarted = create_app(database_path=path, start_command_worker=False)
    with TestClient(restarted) as client:
        headers = _login(client, "admin", "admin-password")
        assert client.get("/api/v1/settings", headers=headers).json()["active_map_id"] == "mock_lab_b"


def test_settings_keep_last_active_values_when_mock_cannot_apply_or_pair_is_moving(tmp_path: Path) -> None:
    app = create_app(database_path=tmp_path / "control.db", start_command_worker=False)
    with TestClient(app) as client:
        app.state.storage.create_or_reset_user("admin", "admin-password", UserRole.ADMIN)
        headers = _login(client, "admin", "admin-password")
        app.state.adapter.set_scenario(MockScenario.SLAVE_OFFLINE)
        assert client.put("/api/v1/settings", json=_payload(), headers=headers).status_code == 503
        assert client.get("/api/v1/settings").json()["version"] == 1
        app.state.adapter.set_scenario(MockScenario.NORMAL)
        source = app.state.adapter.snapshot()
        app.state.state_store.snapshot_source = lambda: source.model_copy(update={"robots": [source.robots[0].model_copy(update={"mode": RobotMode.AUTO}), source.robots[1]]})
        assert client.put("/api/v1/settings", json=_payload(), headers=headers).status_code == 409
        assert client.get("/api/v1/settings").json()["version"] == 1


def test_initial_pose_requires_selected_robot_stopped_and_duplicate_request_executes_once(tmp_path: Path) -> None:
    app = create_app(database_path=tmp_path / "control.db", start_command_worker=False)
    with TestClient(app) as client:
        app.state.storage.create_or_reset_user("admin", "admin-password", UserRole.ADMIN)
        headers = _login(client, "admin", "admin-password")
        request_id = str(uuid4())
        payload = {"request_id": request_id, "pose": {"x": 3.0, "y": 1.0, "yaw": 0.2, "frame_id": "map"}}
        first = client.post("/api/v1/robots/robot_1/initial-pose", json=payload, headers=headers)
        duplicate = client.post("/api/v1/robots/robot_1/initial-pose", json=payload, headers=headers)
        assert first.status_code == duplicate.status_code == 202
        assert first.json()["command_id"] == duplicate.json()["command_id"]
        asyncio.run(app.state.command_dispatcher.process_next())
        assert client.get("/api/v1/state").json()["robots"][0]["pose"]["x"] == 3.0
        source = app.state.adapter.snapshot()
        app.state.state_store.snapshot_source = lambda: source.model_copy(update={"robots": [source.robots[0].model_copy(update={"mode": RobotMode.AUTO}), source.robots[1]]})
        blocked = client.post("/api/v1/robots/robot_1/initial-pose", json={"request_id": str(uuid4()), "pose": payload["pose"]}, headers=headers)
        assert blocked.status_code == 409
