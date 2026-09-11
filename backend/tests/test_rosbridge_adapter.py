from __future__ import annotations

import asyncio
import base64
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from pinky_control_center.adapters.mock import MockRobotAdapter
from pinky_control_center.adapters.ros import RosbridgeAdapter
from pinky_control_center.config import RosbridgeConfig, load_ros_config
from pinky_control_center.models import CommandRequest, Connection
from pinky_control_center.main import create_app


class FakeSocket:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []
        self.incoming: asyncio.Queue[str | None] = asyncio.Queue()
        self.closed = False

    async def send(self, raw: str) -> None:
        payload = json.loads(raw)
        self.sent.append(payload)
        if payload["op"] == "call_service":
            await self.incoming.put(json.dumps({"op": "service_response", "id": payload["id"], "result": True, "values": {"accepted": True}}))

    async def recv(self) -> str | None:
        return await self.incoming.get()

    async def close(self) -> None:
        self.closed = True


def enabled_config() -> RosbridgeConfig:
    data = load_ros_config().model_dump(mode="python")
    for robot in data["robots"]:
        robot["services"]["control_available"] = True
        robot["services"]["follow_available"] = True
    return RosbridgeConfig.model_validate(data)


def test_ros_config_locks_domain_ids_and_uses_two_endpoints() -> None:
    data = load_ros_config().model_dump(mode="python")
    data["robots"][0]["domain_id"] = 99
    with pytest.raises(ValidationError, match="domain_id must be 12"):
        RosbridgeConfig.model_validate(data)
    data = load_ros_config().model_dump(mode="python")
    data["robots"][1]["bridge_url"] = data["robots"][0]["bridge_url"]
    with pytest.raises(ValidationError, match="separate rosbridge endpoint"):
        RosbridgeConfig.model_validate(data)


def test_rosbridge_routes_subscriptions_and_commands_to_the_matching_robot() -> None:
    async def exercise() -> None:
        sockets = {"ws://robot-1.local:9090": FakeSocket(), "ws://robot-2.local:9091": FakeSocket()}

        async def connect(url: str, **_kwargs):
            return sockets[url]

        adapter = RosbridgeAdapter(enabled_config(), connect_factory=connect)
        await adapter.connect()
        await asyncio.sleep(0)
        assert {item["topic"] for item in sockets["ws://robot-1.local:9090"].sent} >= {"/robot_1/odom", "/robot_1/camera/image_raw/compressed"}
        assert {item["topic"] for item in sockets["ws://robot-2.local:9091"].sent} >= {"/robot_2/odom", "/robot_2/camera/image_raw/compressed"}

        accepted = await adapter.execute(CommandRequest(command_id=uuid4(), robot_id="robot_2", operation="stop"))
        assert accepted.accepted is True
        calls_1 = [item for item in sockets["ws://robot-1.local:9090"].sent if item["op"] == "call_service"]
        calls_2 = [item for item in sockets["ws://robot-2.local:9091"].sent if item["op"] == "call_service"]
        assert calls_1 == []
        assert calls_2[0]["service"] == "/robot_2/control/command"
        assert calls_2[0]["args"]["operation"] == "stop"
        await adapter.close()

    asyncio.run(exercise())


def test_rosbridge_decodes_compressed_camera_and_never_treats_odom_as_map_pose() -> None:
    async def exercise() -> None:
        adapter = RosbridgeAdapter(load_ros_config())
        jpeg = MockRobotAdapter().frame("robot_1").jpeg
        await adapter.handle_publish("robot_1", "/robot_1/camera/image_raw/compressed", {"data": base64.b64encode(jpeg).decode(), "header": {"seq": 7}})
        await adapter.handle_publish("robot_1", "/robot_1/odom", {
            "header": {"frame_id": "odom"},
            "pose": {"pose": {"position": {"x": 1.0, "y": 2.0}, "orientation": {"x": 0, "y": 0, "z": 0, "w": 1}}},
            "twist": {"twist": {"linear": {"x": 0.1}, "angular": {"z": 0.2}}},
        })
        frame = adapter.frame("robot_1")
        state = adapter.snapshot().robots[0]
        assert frame is not None and frame.frame_id == "7" and frame.jpeg == jpeg
        assert state.connection is Connection.ONLINE
        assert state.pose is not None and state.pose.frame_id == "odom"
        assert state.tf_valid is False and state.tf_reason_code == "MAP_TF_UNVERIFIED"

    asyncio.run(exercise())


def test_ros_mode_starts_in_observation_mode_without_applying_mock_settings(tmp_path) -> None:
    # Unreachable deployment endpoints must not prevent the API from exposing
    # its stale/offline state or cause a mock settings application to be claimed.
    with TestClient(create_app("ros", database_path=tmp_path / "control.db")) as client:
        assert client.get("/health").json() == {"status": "ok", "mode": "ros"}
