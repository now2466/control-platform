from __future__ import annotations

from collections.abc import Callable

from fastapi import HTTPException, Request, WebSocket

from pinky_control_center.models import UserInfo, UserRole
from pinky_control_center.storage import Storage

SESSION_COOKIE = "cc_session"
CSRF_COOKIE = "cc_csrf"


def _origin_allowed(origin: str | None, allowed_origin: str) -> bool:
    return origin == allowed_origin


def current_user(request: Request) -> UserInfo:
    session = request.app.state.storage.session_user(request.cookies.get(SESSION_COOKIE))
    if session is None:
        raise HTTPException(status_code=401, detail="AUTH_REQUIRED")
    return session[0]


def require_role(*roles: UserRole) -> Callable[[Request], UserInfo]:
    def dependency(request: Request) -> UserInfo:
        user = current_user(request)
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="FORBIDDEN")
        return user
    return dependency


def verify_mutation(request: Request, user: UserInfo) -> None:
    if not _origin_allowed(request.headers.get("origin"), request.app.state.allowed_origin):
        raise HTTPException(status_code=403, detail="ORIGIN_FORBIDDEN")
    session = request.app.state.storage.session_user(request.cookies.get(SESSION_COOKIE))
    csrf = request.headers.get("x-csrf-token")
    if session is None or csrf is None or not __import__("hmac").compare_digest(session[1], csrf):
        raise HTTPException(status_code=403, detail="CSRF_INVALID")


async def websocket_user(websocket: WebSocket) -> UserInfo | None:
    if not _origin_allowed(websocket.headers.get("origin"), websocket.app.state.allowed_origin):
        await websocket.close(code=4403)
        return None
    session = websocket.app.state.storage.session_user(websocket.cookies.get(SESSION_COOKIE))
    if session is None:
        await websocket.close(code=4401)
        return None
    return session[0]
