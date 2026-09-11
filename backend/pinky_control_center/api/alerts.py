from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from pinky_control_center.auth import current_user, verify_mutation
from pinky_control_center.models import Alert, AlertSeverity, AlertState, UserInfo, UserRole


router = APIRouter(prefix="/api/v1")


@router.get("/alerts")
async def alerts(request: Request, state: AlertState | None = None, severity: AlertSeverity | None = None, robot_id: str | None = None, cursor: int = 0, limit: int = 100, _user: UserInfo = Depends(current_user)) -> dict[str, object]:
    if robot_id is not None and robot_id not in {"robot_1", "robot_2"}:
        raise HTTPException(status_code=404, detail="ROBOT_NOT_FOUND")
    if not 1 <= limit <= 100 or cursor < 0:
        raise HTTPException(status_code=422, detail="INVALID_VALUE")
    items, next_cursor = request.app.state.alert_service.page(state=state.value if state else None, severity=severity.value if severity else None, robot_id=robot_id, limit=limit, cursor=cursor)
    return {"items": [item.model_dump(mode="json") for item in items], "next_cursor": next_cursor}


@router.post("/alerts/{alert_id}/ack", response_model=Alert)
async def acknowledge(alert_id: str, payload: dict[str, object], request: Request, user: UserInfo = Depends(current_user)) -> Alert:
    if user.role not in {UserRole.OPERATOR, UserRole.ADMIN}:
        raise HTTPException(status_code=403, detail="FORBIDDEN")
    verify_mutation(request, user)
    try:
        UUID(str(payload["request_id"]))
    except (KeyError, ValueError) as error:
        raise HTTPException(status_code=422, detail="INVALID_VALUE") from error
    alert = request.app.state.alert_service.acknowledge(alert_id, user.username)
    if alert is None:
        raise HTTPException(status_code=404, detail="ALERT_NOT_FOUND")
    return alert
