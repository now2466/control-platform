from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from pinky_control_center.api.control import operator
from pinky_control_center.command_service import QueueFull
from pinky_control_center.models import LocalizationResetRequest, MapNavigationRequest, UserInfo
from pinky_control_center.navigation_service import NavigationConflict


router = APIRouter(prefix="/api/v1")


def _lease_id(payload_lease, request: Request):
    if payload_lease is not None:
        return payload_lease
    try:
        return UUID(request.headers.get("x-control-lease-id") or "")
    except ValueError as error:
        raise HTTPException(status_code=409, detail="CONTROL_CONFLICT") from error


@router.post("/robots/{robot_id}/navigate", status_code=202)
async def navigate(robot_id: str, payload: MapNavigationRequest, request: Request, user: UserInfo = Depends(operator)) -> dict[str, object]:
    if robot_id not in {"robot_1", "robot_2"}:
        raise HTTPException(status_code=404, detail="ROBOT_NOT_FOUND")
    lease_id = _lease_id(payload.lease_id, request)
    if not request.app.state.storage.owns_lease(lease_id, user, request.cookies.get("cc_session", "")):
        raise HTTPException(status_code=409, detail="CONTROL_CONFLICT")
    try:
        return request.app.state.navigation_service.start(user, robot_id, payload, request.app.state.command_dispatcher)
    except NavigationConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except QueueFull as error:
        raise HTTPException(status_code=503, detail="QUEUE_FULL") from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail="REQUEST_ID_CONFLICT") from error


@router.post("/robots/{robot_id}/localization-reset", status_code=202)
async def localization_reset(robot_id: str, payload: LocalizationResetRequest, request: Request, user: UserInfo = Depends(operator)) -> dict[str, object]:
    if robot_id not in {"robot_1", "robot_2"}:
        raise HTTPException(status_code=404, detail="ROBOT_NOT_FOUND")
    lease_id = _lease_id(payload.lease_id, request)
    if not request.app.state.storage.owns_lease(lease_id, user, request.cookies.get("cc_session", "")):
        raise HTTPException(status_code=409, detail="CONTROL_CONFLICT")
    try:
        return request.app.state.navigation_service.reset_localization(user, robot_id, payload, request.app.state.command_dispatcher)
    except NavigationConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except QueueFull as error:
        raise HTTPException(status_code=503, detail="QUEUE_FULL") from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail="REQUEST_ID_CONFLICT") from error
