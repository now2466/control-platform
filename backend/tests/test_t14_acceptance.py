"""Mock acceptance smoke checks used by deployment/acceptance.sh.

These checks exercise the operator-visible gates and failure states that can be
run without ROS or hardware. Dual-domain ROS, TF, watchdog, and Gazebo motion
checks remain NOT_RUN in docs/acceptance-report.md until T12 contracts exist.
"""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from pinky_control_center.main import create_app
from pinky_control_center.models import UserRole


ORIGIN = "http://localhost:5173"


def operator_headers(client: TestClient) -> dict[str, str]:
    client.app.state.storage.create_or_reset_user("acceptance", "acceptance-password", UserRole.ADMIN)
    login = client.post(
        "/api/v1/session",
        json={"username": "acceptance", "password": "acceptance-password"},
        headers={"origin": ORIGIN},
    )
    assert login.status_code == 200
    return {"origin": ORIGIN, "x-csrf-token": login.json()["csrf_token"]}


def test_a01_mock_dashboard_has_two_robots_map_and_two_camera_streams(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "control.db")) as client:
        operator_headers(client)
        state = client.get("/api/v1/state")
        assert state.status_code == 200
        body = state.json()
        assert body["mode"] == "mock"
        assert {robot["robot_id"] for robot in body["robots"]} == {"robot_1", "robot_2"}
        assert client.get("/api/v1/maps").status_code == 200
        for robot_id in ("robot_1", "robot_2"):
            camera = client.get(f"/api/v1/cameras/{robot_id}")
            assert camera.status_code == 200
            assert camera.headers["content-type"].startswith("image/jpeg")


def test_a04_stop_preserves_offline_robot_as_unconfirmed_candidate(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "control.db")) as client:
        headers = operator_headers(client)
        scenario = client.post(
            "/api/v1/mock/scenario",
            json={"scenario": "slave_offline"},
            headers=headers,
        )
        assert scenario.status_code == 200
        stop = client.post(
            "/api/v1/stop",
            json={"request_id": str(uuid4()), "target": "all"},
            headers=headers,
        )
        assert stop.status_code == 202
        assert {target["robot_id"] for target in stop.json()["targets"]} == {"robot_1", "robot_2"}
        assert all(target["state"] == "REQUESTED" for target in stop.json()["targets"])
        state = client.get("/api/v1/state").json()
        slave = next(robot for robot in state["robots"] if robot["robot_id"] == "robot_2")
        assert slave["connection"] == "OFFLINE"
        assert slave["pose"] is None


def test_a06_a07_failure_injection_is_scoped_to_formation_or_camera(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "control.db")) as client:
        headers = operator_headers(client)
        assert client.post(
            "/api/v1/mock/scenario", json={"scenario": "follow_lost"}, headers=headers
        ).status_code == 200
        state = client.get("/api/v1/state").json()
        assert state["formation"]["state"] == "LOST"
        assert {robot["connection"] for robot in state["robots"]} == {"ONLINE"}

        assert client.post(
            "/api/v1/mock/scenario", json={"scenario": "camera_stall"}, headers=headers
        ).status_code == 200
        assert client.get("/api/v1/cameras/robot_1").status_code == 200
        assert client.get("/api/v1/cameras/robot_2").status_code == 503


def test_a08_duplicate_request_id_does_not_create_a_second_command(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "control.db")) as client:
        headers = operator_headers(client)
        request_id = str(uuid4())
        payload = {"request_id": request_id, "mode": "IDLE"}
        first = client.post("/api/v1/robots/robot_1/mode", json=payload, headers=headers)
        second = client.post("/api/v1/robots/robot_1/mode", json=payload, headers=headers)
        assert first.status_code == second.status_code == 202
        assert first.json()["command_id"] == second.json()["command_id"]


def test_n09_secure_cookie_switch_is_explicit(tmp_path: Path) -> None:
    with TestClient(
        create_app(
            database_path=tmp_path / "control.db",
            allowed_origin="https://control.example.invalid",
            secure_cookies=True,
        )
    ) as client:
        client.app.state.storage.create_or_reset_user("secure", "secure-password", UserRole.ADMIN)
        response = client.post(
            "/api/v1/session",
            json={"username": "secure", "password": "secure-password"},
            headers={"origin": "https://control.example.invalid"},
        )
        assert response.status_code == 200
        assert "cc_session=" in response.headers["set-cookie"]
        assert "Secure" in response.headers["set-cookie"]
