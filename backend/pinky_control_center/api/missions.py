from __future__ import annotations

from uuid import UUID
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from pinky_control_center.api.control import operator
from pinky_control_center.auth import current_user
from pinky_control_center.models import UserInfo
from pinky_control_center.command_service import QueueFull

router = APIRouter(prefix="/api/v1")


def request_id(payload: dict[str, object]) -> UUID:
    try: return UUID(str(payload["request_id"]))
    except (KeyError, ValueError) as error: raise HTTPException(422, detail="INVALID_VALUE") from error

def leased_operator(request: Request, payload: dict[str, object], user: UserInfo) -> UserInfo:
    try: lease_id = UUID(str(payload.get("lease_id") or request.headers.get("x-control-lease-id")))
    except (KeyError, ValueError) as error: raise HTTPException(409, detail="CONTROL_CONFLICT") from error
    if not request.app.state.storage.owns_lease(lease_id, user, request.cookies.get("cc_session", "")):
        raise HTTPException(409, detail="CONTROL_CONFLICT")
    return user


@router.post("/formation/actions", status_code=202)
async def formation_action(payload: dict[str, object], request: Request, user: UserInfo = Depends(operator)) -> dict[str, object]:
    try:
        leased_operator(request, payload, user)
        action = str(payload["action"]); master = str(payload["master_id"]); slave = str(payload["slave_id"])
        if action not in {"pair", "pause", "unpair", "rejoin"}: raise ValueError
        return request.app.state.mission_service.formation_action(user, request_id(payload), action, master, slave, request.app.state.command_dispatcher)
    except QueueFull as error: raise HTTPException(503, detail="QUEUE_FULL") from error
    except ValueError as error: raise HTTPException(422, detail="INVALID_VALUE") from error


@router.post("/missions", status_code=201)
async def create_mission(payload: dict[str, object], request: Request, user: UserInfo = Depends(operator)) -> dict[str, object]:
    request_id(payload); leased_operator(request, payload, user)
    return request.app.state.mission_service.create(user, payload)


@router.get("/missions/{mission_id}")
async def get_mission(mission_id: str, request: Request, user: UserInfo = Depends(current_user)) -> dict[str, object]:
    value = request.app.state.storage.mission(mission_id, user)
    if value is None: raise HTTPException(404, detail="MISSION_NOT_FOUND")
    return value

@router.get("/missions")
async def list_missions(request: Request, user: UserInfo = Depends(current_user), limit: int = 20, cursor: int = 0, state: str | None = None, from_time: datetime | None = Query(None, alias="from"), to_time: datetime | None = Query(None, alias="to")) -> dict[str, object]:
    if not 1 <= limit <= 100 or cursor < 0: raise HTTPException(422, detail="INVALID_VALUE")
    if from_time and to_time and from_time > to_time: raise HTTPException(422, detail="INVALID_VALUE")
    items, next_cursor = request.app.state.storage.missions(user, state=state, limit=limit, cursor=cursor, from_time=from_time.isoformat() if from_time else None, to_time=to_time.isoformat() if to_time else None)
    return {"items": items, "next_cursor": next_cursor}

@router.patch("/missions/{mission_id}")
async def edit_mission(mission_id: str, payload: dict[str, object], request: Request, user: UserInfo = Depends(operator)) -> dict[str, object]:
    try:
        request_id(payload); leased_operator(request, payload, user)
        return request.app.state.mission_service.edit(user, mission_id, payload)
    except ValueError as error: raise HTTPException(409, detail="REQUEST_ID_CONFLICT") from error


@router.post("/missions/{mission_id}/actions", status_code=202)
async def mission_action(mission_id: str, payload: dict[str, object], request: Request, user: UserInfo = Depends(operator)) -> dict[str, object]:
    try:
        leased_operator(request, payload, user)
        action = str(payload["action"])
        return request.app.state.mission_service.action(user, mission_id, request_id(payload), action, request.app.state.command_dispatcher)
    except QueueFull as error: raise HTTPException(503, detail="QUEUE_FULL") from error
