from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from pinky_control_center.main import create_app
from pinky_control_center.models import Freshness, UserRole


ORIGIN = "http://localhost:5173"


def _operator_headers(client: TestClient) -> dict[str, str]:
    client.app.state.storage.create_or_reset_user("navigator", "navigator-password", UserRole.OPERATOR)
    response = client.post(
        "/api/v1/session",
        json={"username": "navigator", "password": "navigator-password"},
        headers={"origin": ORIGIN},
    )
    assert response.status_code == 200
    return {"origin": ORIGIN, "x-csrf-token": response.json()["csrf_token"]}


def _lease(client: TestClient, headers: dict[str, str]) -> str:
    response = client.post("/api/v1/control-lease", json={"request_id": str(uuid4())}, headers=headers)
    assert response.status_code == 200
    return response.json()["lease_id"]


def _pose(x: float, y: float, yaw: float = 0.0) -> dict[str, object]:
    return {"x": x, "y": y, "yaw": yaw, "frame_id": "map"}


def test_map_navigation_sets_initial_pose_before_auto_goal_and_is_idempotent(tmp_path: Path) -> None:
    app = create_app(database_path=tmp_path / "control.db", start_command_worker=False, start_watchdog=False)
    with TestClient(app) as client:
        headers = _operator_headers(client)
        lease = _lease(client, headers)
        request_id = str(uuid4())
        payload = {
            "request_id": request_id,
            "lease_id": lease,
            "map_id": "mock_lab",
            "start_pose": _pose(1.0, 1.0),
            "goal": _pose(1.5, 1.5, 0.4),
        }

        first = client.post("/api/v1/robots/robot_1/navigate", json=payload, headers=headers)
        duplicate = client.post("/api/v1/robots/robot_1/navigate", json=payload, headers=headers)
        assert first.status_code == duplicate.status_code == 202
        assert first.json()["command_id"] == duplicate.json()["command_id"]
        assert first.json()["navigation_id"] == request_id

        asyncio.run(app.state.command_dispatcher.process_next())
        command = client.get(f"/api/v1/commands/{first.json()['command_id']}")
        assert command.status_code == 200
        assert command.json()["state"] == "SUCCEEDED"
        assert command.json()["navigation_state"] == "REQUESTED"
        adapter = app.state.adapter
        assert adapter._initial_poses["robot_1"].model_dump(mode="json") == _pose(1.0, 1.0)
        assert adapter._goals["robot_1"].model_dump(mode="json") == _pose(1.5, 1.5, 0.4)


def test_map_navigation_rejects_occupied_cells_and_localization_reset_keeps_map(tmp_path: Path) -> None:
    app = create_app(database_path=tmp_path / "control.db", start_command_worker=False, start_watchdog=False)
    with TestClient(app) as client:
        headers = _operator_headers(client)
        lease = _lease(client, headers)
        blocked = client.post(
            "/api/v1/robots/robot_1/navigate",
            json={
                "request_id": str(uuid4()),
                "lease_id": lease,
                "map_id": "mock_lab",
                "start_pose": _pose(0.8, 1.0),
                "goal": _pose(1.5, 1.5),
            },
            headers=headers,
        )
        assert blocked.status_code == 409
        assert blocked.json()["error"]["code"] == "MAP_POINT_BLOCKED"

        reset = client.post(
            "/api/v1/robots/robot_1/localization-reset",
            json={
                "request_id": str(uuid4()),
                "lease_id": lease,
                "map_id": "mock_lab",
                "pose": _pose(1.0, 0.6, -0.2),
            },
            headers=headers,
        )
        assert reset.status_code == 202
        asyncio.run(app.state.command_dispatcher.process_next())
        assert app.state.adapter._initial_poses["robot_1"].model_dump(mode="json") == _pose(1.0, 0.6, -0.2)
        assert client.get("/api/v1/state").json()["map_id"] == "mock_lab"


def test_localization_reset_is_available_when_current_map_pose_is_stale(tmp_path: Path) -> None:
    app = create_app(database_path=tmp_path / "control.db", start_command_worker=False, start_watchdog=False)
    source = app.state.state_store.snapshot_source()
    robots = [
        robot.model_copy(update={"pose": None, "pose_freshness": Freshness.UNKNOWN, "tf_valid": False})
        if robot.robot_id == "robot_1" else robot
        for robot in source.robots
    ]
    app.state.state_store.snapshot_source = lambda: source.model_copy(update={"robots": robots})

    with TestClient(app) as client:
        headers = _operator_headers(client)
        lease = _lease(client, headers)
        reset = client.post(
            "/api/v1/robots/robot_1/localization-reset",
            json={
                "request_id": str(uuid4()),
                "lease_id": lease,
                "map_id": "mock_lab",
                "pose": _pose(1.0, 0.6),
            },
            headers=headers,
        )

        assert reset.status_code == 202
