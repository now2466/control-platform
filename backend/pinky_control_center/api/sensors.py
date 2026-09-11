from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from pinky_control_center.auth import current_user
from pinky_control_center.models import UserInfo


router = APIRouter(prefix="/api/v1")


@router.get("/robots/{robot_id}/sensor-layers")
async def sensor_layers(robot_id: str, request: Request, _user: UserInfo = Depends(current_user)) -> dict[str, object]:
    if robot_id not in {"robot_1", "robot_2"}:
        raise HTTPException(status_code=404, detail="ROBOT_NOT_FOUND")
    return request.app.state.adapter.sensor_layers(robot_id)
