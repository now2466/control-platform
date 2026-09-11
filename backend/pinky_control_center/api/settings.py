from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from pinky_control_center.auth import current_user, verify_mutation
from pinky_control_center.command_service import QueueFull
from pinky_control_center.models import ActiveSettings, InitialPoseRequest, SettingsUpdate, UserInfo, UserRole
from pinky_control_center.settings_service import SettingsApplyFailed, SettingsConflict, UnsafeSettingsChange


def admin(request: Request) -> UserInfo:
    user = current_user(request)
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="FORBIDDEN")
    verify_mutation(request, user)
    return user


def create_router() -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    @router.get("/settings", response_model=ActiveSettings)
    async def get_settings(request: Request, _user: UserInfo = Depends(current_user)) -> ActiveSettings:
        return request.app.state.settings_service.current()

    @router.put("/settings", response_model=ActiveSettings)
    async def put_settings(payload: SettingsUpdate, request: Request, _user: UserInfo = Depends(admin)) -> ActiveSettings:
        try:
            return await request.app.state.settings_service.update(ActiveSettings.model_validate(payload.model_dump(exclude={"request_id"})))
        except SettingsConflict as error:
            raise HTTPException(status_code=409, detail="SETTINGS_VERSION_CONFLICT") from error
        except UnsafeSettingsChange as error:
            raise HTTPException(status_code=409, detail="SETTINGS_CHANGE_UNSAFE") from error
        except SettingsApplyFailed as error:
            raise HTTPException(status_code=503, detail="SETTINGS_APPLY_FAILED") from error
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @router.post("/robots/{robot_id}/initial-pose", status_code=202)
    async def set_initial_pose(robot_id: str, payload: InitialPoseRequest, request: Request, user: UserInfo = Depends(admin)) -> dict[str, object]:
        if robot_id not in {"robot_1", "robot_2"}:
            raise HTTPException(status_code=404, detail="ROBOT_NOT_FOUND")
        if not request.app.state.settings_service.initial_pose_allowed(robot_id):
            raise HTTPException(status_code=409, detail="ROBOT_NOT_STOPPED")
        try:
            return request.app.state.command_dispatcher.submit(
                user, payload.request_id, robot_id, "initial_pose", parameters={"pose": payload.pose.model_dump(mode="json")},
            )
        except ValueError as error:
            raise HTTPException(status_code=409, detail="REQUEST_ID_CONFLICT") from error
        except QueueFull as error:
            raise HTTPException(status_code=503, detail="QUEUE_FULL") from error

    return router
