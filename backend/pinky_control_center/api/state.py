from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Request, WebSocket

from pinky_control_center.auth import current_user, websocket_user
from pinky_control_center.models import StateSnapshot
from pinky_control_center.state_store import StateStore


def create_router(state_store: StateStore) -> APIRouter:
    router = APIRouter()


    @router.get("/api/v1/state", response_model=StateSnapshot)
    async def state(_request: Request, _user=Depends(current_user)) -> StateSnapshot:
        return state_store.snapshot()


    @router.websocket("/ws/state")
    async def state_socket(websocket: WebSocket) -> None:
        user = await websocket_user(websocket)
        if user is None:
            return
        await websocket.accept()
        while True:
            snapshot = state_store.snapshot()
            await websocket.send_json({"type": "snapshot", "seq": snapshot.seq, "server_time": snapshot.server_time.isoformat(), "payload": snapshot.model_dump(mode="json")})
            await asyncio.sleep(0.2)

    return router
