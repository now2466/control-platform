from __future__ import annotations

import argparse
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response

from pinky_control_center.adapters.mock import MockRobotAdapter
from pinky_control_center.config import load_mock_config
from pinky_control_center.models import MockScenario, MockScenarioRequest, StateSnapshot


def create_app(mode: Literal["mock", "ros"] = "mock", config_path: Path | None = None) -> FastAPI:
    if mode != "mock":
        raise ValueError("ROS mode is not available in T01; start with --mode mock")
    adapter = MockRobotAdapter(config=load_mock_config(config_path))

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await adapter.connect()
        yield
        await adapter.close()

    app = FastAPI(title="Pinky Control Center", version="0.1.0", lifespan=lifespan)
    app.state.adapter = adapter
    app.state.mode = mode

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "mode": mode}

    @app.get("/api/v1/state", response_model=StateSnapshot)
    async def state() -> StateSnapshot:
        return adapter.snapshot()

    @app.get("/api/v1/cameras/{robot_id}")
    async def camera(robot_id: Literal["robot_1", "robot_2"]) -> Response:
        frame = adapter.frame(robot_id)
        if frame is None:
            raise HTTPException(status_code=503, detail={"code": "CAMERA_STALLED", "robot_id": robot_id})
        return Response(content=frame.jpeg, media_type="image/jpeg", headers={"X-Frame-Id": frame.frame_id})

    @app.get("/api/v1/mock/scenario", response_model=MockScenarioRequest)
    async def get_scenario() -> MockScenarioRequest:
        return MockScenarioRequest(scenario=adapter.scenario)

    @app.post("/api/v1/mock/scenario", response_model=MockScenarioRequest)
    async def set_scenario(payload: MockScenarioRequest) -> MockScenarioRequest:
        adapter.set_scenario(payload.scenario)
        return payload

    return app


def cli() -> None:
    parser = argparse.ArgumentParser(description="Run the Pinky Pro mock control API")
    parser.add_argument("--mode", choices=("mock", "ros"), default="mock")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument("--config", type=Path, default=None, help="path to mock robot mapping YAML")
    args = parser.parse_args()
    if args.mode != "mock":
        parser.error("ROS mode is planned for T12 and cannot run in T01")
    uvicorn.run(create_app("mock", args.config), host=args.host, port=args.port)


if __name__ == "__main__":
    cli()
