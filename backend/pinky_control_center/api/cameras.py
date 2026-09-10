from __future__ import annotations

from fastapi import APIRouter, WebSocket

from pinky_control_center.auth import websocket_user
from pinky_control_center.camera_service import CameraQuality, CameraService, VALID_ROBOT_IDS, encode_camera_frame


def create_router(camera_service: CameraService) -> APIRouter:
    router = APIRouter()

    @router.websocket("/ws/cameras/{robot_id}")
    async def camera_socket(websocket: WebSocket, robot_id: str) -> None:
        if await websocket_user(websocket) is None:
            return
        if robot_id not in VALID_ROBOT_IDS:
            await websocket.close(code=4404)
            return
        quality = websocket.query_params.get("quality", "default")
        if quality not in {"low", "default", "high"}:
            await websocket.close(code=4400)
            return
        await websocket.accept()
        async with camera_service.subscribe(robot_id, quality) as queue:  # type: ignore[arg-type]
            while True:
                await websocket.send_bytes(encode_camera_frame(await queue.get()))

    return router
