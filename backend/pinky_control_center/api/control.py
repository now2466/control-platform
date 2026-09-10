from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from pinky_control_center.auth import current_user, verify_mutation
from pinky_control_center.models import ControlLease, LeaseRequest, UserInfo, UserRole
from pinky_control_center.storage import LeaseConflict, LeaseNotFound

router = APIRouter(prefix="/api/v1")


def operator(request: Request) -> UserInfo:
    user = current_user(request)
    if user.role not in {UserRole.OPERATOR, UserRole.ADMIN}:
        raise HTTPException(status_code=403, detail="FORBIDDEN")
    verify_mutation(request, user)
    return user


@router.post("/control-lease", response_model=ControlLease)
async def acquire(payload: LeaseRequest, request: Request, user: UserInfo = Depends(operator)) -> ControlLease:
    try:
        return request.app.state.storage.acquire_lease(user, payload.request_id, request.cookies.get("cc_session", ""))
    except LeaseConflict as error:
        raise HTTPException(status_code=409, detail="CONTROL_CONFLICT") from error


@router.patch("/control-lease/{lease_id}", response_model=ControlLease)
async def renew(lease_id: str, payload: LeaseRequest, request: Request, user: UserInfo = Depends(operator)) -> ControlLease:
    from uuid import UUID
    try:
        return request.app.state.storage.renew_lease(UUID(lease_id), user, payload.request_id, request.cookies.get("cc_session", ""))
    except (LeaseNotFound, ValueError) as error:
        raise HTTPException(status_code=409, detail="CONTROL_CONFLICT") from error


@router.delete("/control-lease/{lease_id}", status_code=204)
async def release(lease_id: str, request: Request, user: UserInfo = Depends(operator)) -> Response:
    from uuid import UUID
    try:
        request.app.state.storage.release_lease(UUID(lease_id), user, request.cookies.get("cc_session", ""))
    except (LeaseNotFound, ValueError) as error:
        raise HTTPException(status_code=409, detail="CONTROL_CONFLICT") from error
    return Response(status_code=204)
