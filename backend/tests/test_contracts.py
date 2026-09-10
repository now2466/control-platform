from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from pinky_control_center.adapters.mock import MockRobotAdapter
from pinky_control_center.config import MockConfig, load_mock_config
from pinky_control_center.main import create_app
from pinky_control_center.models import Alert, CommandRequest, FormationState, Mission, MockScenario, Pose, RobotState
from pinky_control_center.models import UserRole


ORIGIN = "http://localhost:5173"


def login_operator(client: TestClient) -> str:
    client.app.state.storage.create_or_reset_user("contract-admin", "correct-horse-battery", UserRole.ADMIN)
    response = client.post("/api/v1/session", json={"username": "contract-admin", "password": "correct-horse-battery"}, headers={"origin": ORIGIN})
    assert response.status_code == 200
    return response.json()["csrf_token"]


def test_rejects_nan_and_out_of_range_contract_values() -> None:
    with pytest.raises(ValidationError):
        Pose(x=float("nan"), y=0, yaw=0, frame_id="map")
    with pytest.raises(ValidationError):
        RobotState.model_validate({
            "robot_id": "robot_1", "name": "Master", "role": "MASTER", "connection": "ONLINE",
            "pose_freshness": "FRESH", "battery_percent": 101, "battery_freshness": "FRESH", "mode": "IDLE",
        })
    with pytest.raises(ValidationError):
        FormationState(state="READY", master_id="robot_1", slave_id="robot_1", target_distance_m=0.8)


def test_mission_and_alert_contracts_enforce_bounds() -> None:
    now = datetime.now(UTC)
    mission = Mission(
        mission_id=uuid4(), name="mock mission", state="DRAFT", master_id="robot_1", slave_id="robot_2",
        map_id="mock_lab", waypoints=[Pose(x=0, y=0, yaw=0, frame_id="map")], repeat_count=1,
        waypoint_index=0, lap_index=0, created_at=now, updated_at=now,
    )
    assert mission.name == "mock mission"
    with pytest.raises(ValidationError):
        Mission(
            mission_id=uuid4(), name="bad", state="DRAFT", master_id="robot_1", slave_id="robot_2",
            map_id="mock_lab", waypoints=[Pose(x=0, y=0, yaw=0, frame_id="map")], repeat_count=101,
            waypoint_index=0, lap_index=0, created_at=now, updated_at=now,
        )
    with pytest.raises(ValidationError):
        Alert(alert_id=uuid4(), code="LOW_BATTERY", severity="WARNING", state="ACTIVE", occurrences=0,
              message="low", first_seen_at=now, last_seen_at=now)


def test_mock_config_rejects_duplicate_namespaces_and_is_used_by_adapter() -> None:
    with pytest.raises(ValidationError):
        MockConfig.model_validate({"robots": [
            {"robot_id": "robot_1", "name": "one", "role": "MASTER", "namespace": "/same"},
            {"robot_id": "robot_2", "name": "two", "role": "SLAVE", "namespace": "/same"},
        ]})
    config = load_mock_config()
    assert MockRobotAdapter(config=config).snapshot().robots[0].name == "Pinky Master"


def test_state_contract_has_exactly_two_distinct_robots(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "control.db")) as client:
        login_operator(client)
        response = client.get("/api/v1/state")
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "mock"
    assert {robot["robot_id"] for robot in body["robots"]} == {"robot_1", "robot_2"}
    assert body["robots"][0]["role"] == "MASTER"
    assert body["robots"][1]["role"] == "SLAVE"


def test_mock_scenarios_change_only_the_expected_robot_or_formation(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "control.db")) as client:
        csrf = login_operator(client)
        headers = {"origin": ORIGIN, "x-csrf-token": csrf}
        assert client.post("/api/v1/mock/scenario", json={"scenario": "slave_offline"}, headers=headers).status_code == 200
        state = client.get("/api/v1/state").json()
        assert state["robots"][1]["connection"] == "OFFLINE"
        assert client.post("/api/v1/mock/scenario", json={"scenario": "follow_lost"}, headers=headers).status_code == 200
        assert client.get("/api/v1/state").json()["formation"]["state"] == "LOST"


def test_camera_images_are_jpeg_and_are_distinct_per_robot(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "control.db")) as client:
        csrf = login_operator(client)
        master = client.get("/api/v1/cameras/robot_1")
        slave = client.get("/api/v1/cameras/robot_2")
        assert master.headers["content-type"] == "image/jpeg"
        assert master.content.startswith(b"\xff\xd8")
        assert slave.content.startswith(b"\xff\xd8")
        assert master.content != slave.content
        client.post("/api/v1/mock/scenario", json={"scenario": "camera_stall"}, headers={"origin": ORIGIN, "x-csrf-token": csrf})
        assert client.get("/api/v1/cameras/robot_2").status_code == 503
        assert client.get("/api/v1/cameras/robot_1").status_code == 200


def test_ros_mode_is_not_silently_replaced_by_mock(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        create_app("ros", database_path=tmp_path / "control.db")


def test_mock_execute_returns_acceptance_before_completion_event() -> None:
    async def exercise() -> None:
        adapter = MockRobotAdapter()
        await adapter.connect()
        command = CommandRequest(command_id=uuid4(), robot_id="robot_1", operation="stop")
        acceptance = await adapter.execute(command)
        assert acceptance.accepted is True
        stream = adapter.events()
        completion = await anext(stream)
        assert completion.kind == "command"
        assert completion.payload["state"] == "SUCCEEDED"
        await adapter.close()

    asyncio.run(exercise())
