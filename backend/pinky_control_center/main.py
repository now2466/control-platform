from __future__ import annotations

import argparse
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from pinky_control_center.adapters.mock import MockRobotAdapter
from pinky_control_center.api import control, session, state
from pinky_control_center.auth import current_user, verify_mutation
from pinky_control_center.config import load_mock_config
from pinky_control_center.models import MockScenario, MockScenarioRequest, UserInfo, UserRole
from pinky_control_center.state_store import StateStore
from pinky_control_center.storage import Storage


def default_database_path() -> Path:
    state_home = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return state_home / "control-platform" / "control.db"


def create_app(mode: Literal["mock", "ros"] = "mock", config_path: Path | None = None, database_path: Path | None = None, allowed_origin: str = "http://localhost:5173") -> FastAPI:
    if mode != "mock":
        raise ValueError("ROS mode is not available in T01; start with --mode mock")
    adapter = MockRobotAdapter(config=load_mock_config(config_path))
    lease_events: list[str] = []
    storage = Storage(database_path or default_database_path(), lease_end_hook=lease_events.append)
    state_store = StateStore(adapter.snapshot)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await adapter.connect()
        yield
        await adapter.close()
        storage.close()

    app = FastAPI(title="Pinky Control Center", version="0.1.0", lifespan=lifespan)
    app.state.adapter = adapter
    app.state.mode = mode
    app.state.storage = storage
    app.state.allowed_origin = allowed_origin
    app.state.state_store = state_store
    # T02 records lease end causes only. T05 connects this hook to the safety stop path.
    app.state.lease_events = lease_events
    app.include_router(session.router)
    app.include_router(control.router)
    app.include_router(state.create_router(state_store))

    @app.exception_handler(StarletteHTTPException)
    async def api_error(_request: Request, error: StarletteHTTPException) -> JSONResponse:
        detail = error.detail
        if isinstance(detail, dict):
            code = str(detail.get("code", "REQUEST_FAILED"))
            details = detail
        else:
            code = str(detail)
            details = None
        return JSONResponse(status_code=error.status_code, content={"error": {"code": code, "message": code, "details": details}, "request_id": None})

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, error: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"error": {"code": "INVALID_VALUE", "message": "request validation failed", "details": {"validation_errors": error.errors()}}, "request_id": None})

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "mode": mode}

    @app.get("/api/v1/cameras/{robot_id}")
    async def camera(robot_id: Literal["robot_1", "robot_2"], _user: UserInfo = Depends(current_user)) -> Response:
        frame = adapter.frame(robot_id)
        if frame is None:
            raise HTTPException(status_code=503, detail={"code": "CAMERA_STALLED", "robot_id": robot_id})
        return Response(content=frame.jpeg, media_type="image/jpeg", headers={"X-Frame-Id": frame.frame_id})

    @app.get("/api/v1/mock/scenario", response_model=MockScenarioRequest)
    async def get_scenario(_user: UserInfo = Depends(current_user)) -> MockScenarioRequest:
        return MockScenarioRequest(scenario=adapter.scenario)

    @app.post("/api/v1/mock/scenario", response_model=MockScenarioRequest)
    async def set_scenario(payload: MockScenarioRequest, request: Request, user: UserInfo = Depends(current_user)) -> MockScenarioRequest:
        if user.role not in {UserRole.OPERATOR, UserRole.ADMIN}:
            raise HTTPException(status_code=403, detail="FORBIDDEN")
        verify_mutation(request, user)
        adapter.set_scenario(payload.scenario)
        return payload

    return app


def cli() -> None:
    parser = argparse.ArgumentParser(description="Run the Pinky Pro mock control API")
    parser.add_argument("--mode", choices=("mock", "ros"), default="mock")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument("--config", type=Path, default=None, help="path to mock robot mapping YAML")
    parser.add_argument("--database", type=Path, default=default_database_path())
    parser.add_argument("--reset-password", metavar="USERNAME")
    parser.add_argument("--password", help="password for --reset-password; never persisted in plaintext")
    parser.add_argument("--role", choices=[role.value for role in UserRole], default=UserRole.ADMIN.value)
    args = parser.parse_args()
    if args.mode != "mock":
        parser.error("ROS mode is planned for T12 and cannot run in T01")
    if args.reset_password:
        if not args.password:
            parser.error("--password is required with --reset-password")
        Storage(args.database).create_or_reset_user(args.reset_password, args.password, UserRole(args.role))
        return
    uvicorn.run(create_app("mock", args.config, args.database), host=args.host, port=args.port)


if __name__ == "__main__":
    cli()
