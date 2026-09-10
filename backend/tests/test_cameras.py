from __future__ import annotations

import json
import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from pinky_control_center.adapters.mock import MockRobotAdapter
from pinky_control_center.camera_service import CameraService
from pinky_control_center.main import create_app
from pinky_control_center.models import CameraFrame, UserRole

ORIGIN = "http://localhost:5173"


def login(client: TestClient) -> None:
    client.app.state.storage.create_or_reset_user("camera-viewer", "camera-viewer-password", UserRole.VIEWER)
    response = client.post("/api/v1/session", json={"username": "camera-viewer", "password": "camera-viewer-password"}, headers={"origin": ORIGIN})
    assert response.status_code == 200


def decode(message: bytes) -> tuple[dict[str, object], bytes]:
    metadata_length = int.from_bytes(message[:4], "big")
    return json.loads(message[4:4 + metadata_length]), message[4 + metadata_length:]


def test_camera_websocket_sends_framed_jpeg_metadata(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "control.db")) as client:
        login(client)
        with client.websocket_connect("/ws/cameras/robot_1?quality=default", headers={"origin": ORIGIN}) as socket:
            metadata, jpeg = decode(socket.receive_bytes())
    assert metadata["frame_id"].startswith("mock-robot_1-")
    assert metadata["captured_at"]
    assert metadata["received_at"]
    assert metadata["width"] == 640
    assert metadata["height"] == 480
    assert jpeg.startswith(b"\xff\xd8")


def test_camera_socket_rejects_unauthenticated_bad_origin_unknown_robot_and_quality(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "control.db")) as client:
        with pytest.raises(WebSocketDisconnect) as closed:
            with client.websocket_connect("/ws/cameras/robot_1", headers={"origin": ORIGIN}):
                pass
        assert closed.value.code == 4401
        login(client)
        with pytest.raises(WebSocketDisconnect) as closed:
            with client.websocket_connect("/ws/cameras/robot_1", headers={"origin": "https://invalid.example"}):
                pass
        assert closed.value.code == 4403
        with pytest.raises(WebSocketDisconnect) as closed:
            with client.websocket_connect("/ws/cameras/not-a-robot", headers={"origin": ORIGIN}):
                pass
        assert closed.value.code == 4404
        with pytest.raises(WebSocketDisconnect) as closed:
            with client.websocket_connect("/ws/cameras/robot_1?quality=broken", headers={"origin": ORIGIN}):
                pass
        assert closed.value.code == 4400


def test_latest_frame_queue_drops_old_frame_throttles_and_cleans_up() -> None:
    now = 0.0
    service = CameraService(lambda _robot_id: None, clock=lambda: now)
    frame = CameraFrame(robot_id="robot_1", frame_id="first", captured_at=datetime.now(UTC), received_at=datetime.now(UTC), width=1, height=1, jpeg=b"\xff\xd8\xff\xd9")

    async def exercise() -> None:
        nonlocal now
        async with service.subscribe("robot_1", "default") as queue:
            assert service.viewer_count("robot_1") == 1
            assert service.worker_count == 1
            service.publish(frame)
            now += 0.05
            service.publish(frame.model_copy(update={"frame_id": "throttled"}))
            now += 0.05
            service.publish(frame.model_copy(update={"frame_id": "latest"}))
            assert (await queue.get()).frame_id == "latest"
        await asyncio.sleep(0)
        assert service.viewer_count("robot_1") == 0
        assert service.worker_count == 0
        await service.close()

    asyncio.run(exercise())


def test_quality_resizes_low_but_never_upscales_high() -> None:
    service = CameraService(lambda _robot_id: None)
    jpeg = MockRobotAdapter().frame("robot_1").jpeg
    frame = CameraFrame(robot_id="robot_1", frame_id="source", captured_at=datetime.now(UTC), received_at=datetime.now(UTC), width=640, height=480, jpeg=jpeg)

    async def exercise() -> None:
        async with service.subscribe("robot_1", "low") as low, service.subscribe("robot_1", "high") as high:
            service.publish(frame)
            low_frame, high_frame = await low.get(), await high.get()
            assert (low_frame.width, low_frame.height) == (320, 240)
            assert (high_frame.width, high_frame.height) == (640, 480)
        await service.close()

    asyncio.run(exercise())
