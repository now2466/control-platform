from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response

from pinky_control_center.auth import current_user
from pinky_control_center.models import UserInfo
from pinky_control_center.storage import _timestamp

router = APIRouter(prefix="/api/v1")
DEFAULT_WINDOW = timedelta(hours=24)
MAX_WINDOW = timedelta(days=30)
MAX_EXPORT_EVENTS = 10_000


def _window(request: Request, robot_id: str | None, from_time: datetime | None, to_time: datetime | None) -> tuple[str, str]:
    if robot_id is not None and robot_id not in {"robot_1", "robot_2"}:
        raise HTTPException(status_code=404, detail="ROBOT_NOT_FOUND")
    if (from_time and from_time.tzinfo is None) or (to_time and to_time.tzinfo is None):
        raise HTTPException(status_code=422, detail="UTC_TIMESTAMP_REQUIRED")
    end = (to_time or request.app.state.storage.clock()).astimezone(UTC)
    start = (from_time or end - DEFAULT_WINDOW).astimezone(UTC)
    if start > end or end - start > MAX_WINDOW:
        raise HTTPException(status_code=422, detail="HISTORY_WINDOW_INVALID")
    return _timestamp(start), _timestamp(end)


def _filters(request: Request, user: UserInfo, event_type: str | None, robot_id: str | None, mission_id: str | None, from_time: datetime | None, to_time: datetime | None, cursor: int | None, limit: int) -> tuple[list[dict[str, object]], int | None]:
    if (cursor is not None and cursor < 1) or not 1 <= limit <= 100:
        raise HTTPException(status_code=422, detail="INVALID_VALUE")
    start, end = _window(request, robot_id, from_time, to_time)
    return request.app.state.storage.history(user, event_type=event_type, robot_id=robot_id, mission_id=mission_id, from_time=start, to_time=end, limit=limit, cursor=cursor)


@router.get("/history")
async def history(request: Request, event_type: str | None = None, robot_id: str | None = None, mission_id: str | None = None, from_time: datetime | None = Query(None, alias="from"), to_time: datetime | None = Query(None, alias="to"), cursor: int | None = None, limit: int = 50, user: UserInfo = Depends(current_user)) -> dict[str, object]:
    items, next_cursor = _filters(request, user, event_type, robot_id, mission_id, from_time, to_time, cursor, limit)
    return {"items": items, "next_cursor": next_cursor}


@router.get("/history/export")
async def export_history(request: Request, event_type: str | None = None, robot_id: str | None = None, mission_id: str | None = None, from_time: datetime | None = Query(None, alias="from"), to_time: datetime | None = Query(None, alias="to"), user: UserInfo = Depends(current_user)) -> Response:
    """Return one complete, bounded export; never present a truncated file as complete."""
    start, end = _window(request, robot_id, from_time, to_time)
    items, next_cursor = request.app.state.storage.history(user, event_type=event_type, robot_id=robot_id, mission_id=mission_id, from_time=start, to_time=end, limit=MAX_EXPORT_EVENTS)
    if next_cursor is not None:
        raise HTTPException(status_code=413, detail={"code": "HISTORY_EXPORT_LIMIT", "max_events": MAX_EXPORT_EVENTS})
    return Response(content=json.dumps({"items": items, "next_cursor": None}, ensure_ascii=False), media_type="application/json", headers={"Content-Disposition": "attachment; filename=history.json", "Cache-Control": "no-store"})
