from __future__ import annotations

import asyncio
import io
from datetime import UTC, datetime
from typing import AsyncIterator, Literal

from PIL import Image, ImageDraw, ImageFont

from pinky_control_center.config import MockConfig, load_mock_config
from pinky_control_center.models import (
    AdapterEvent, CameraFrame, CommandAcceptance, CommandRequest, Connection, FormationMode,
    FormationState, Freshness, MockScenario, Pose, RobotMode, RobotState, Role, SensorState,
    SensorStatus, StateSnapshot,
)

RobotId = Literal["robot_1", "robot_2"]


class MockRobotAdapter:
    """Deterministic two-robot source used before ROS hardware integration."""

    def __init__(self, scenario: MockScenario = MockScenario.NORMAL, config: MockConfig | None = None) -> None:
        self._scenario = scenario
        self._sequence = 0
        self._connected = False
        self._command_events: list[AdapterEvent] = []
        self._config = config or load_mock_config()

    def _robot(self, robot_id: RobotId):
        return next(robot for robot in self._config.robots if robot.robot_id == robot_id)

    @property
    def scenario(self) -> MockScenario:
        return self._scenario

    def set_scenario(self, scenario: MockScenario) -> None:
        self._scenario = scenario
        self._sequence += 1

    async def connect(self) -> None:
        self._connected = True

    async def close(self) -> None:
        self._connected = False

    async def execute(self, command: CommandRequest) -> CommandAcceptance:
        if self._scenario is MockScenario.COMMAND_REJECTED:
            self._command_events.append(AdapterEvent(
                kind="command", robot_id=command.robot_id, received_at=datetime.now(UTC),
                payload={"command_id": str(command.command_id), "state": "REJECTED", "reason_code": "MOCK_COMMAND_REJECTED", "operation": command.operation, "parameters": command.parameters},
            ))
            return CommandAcceptance(accepted=False, reason_code="MOCK_COMMAND_REJECTED")
        self._command_events.append(AdapterEvent(
            kind="command", robot_id=command.robot_id, received_at=datetime.now(UTC),
            payload={"command_id": str(command.command_id), "state": "SUCCEEDED", "reason_code": None, "operation": command.operation, "parameters": command.parameters},
        ))
        return CommandAcceptance(accepted=True)

    def drain_events(self) -> list[AdapterEvent]:
        events, self._command_events = self._command_events, []
        return events

    def snapshot(self) -> StateSnapshot:
        now = datetime.now(UTC)
        offline = self._scenario is MockScenario.SLAVE_OFFLINE
        master_config = self._robot("robot_1")
        slave_config = self._robot("robot_2")
        master = RobotState(
            robot_id="robot_1", name=master_config.name, role=master_config.role,
            connection=Connection.ONLINE, received_at=now,
            pose=Pose(x=1.2, y=2.0, yaw=0.0, frame_id="map"), pose_freshness=Freshness.FRESH,
            linear_mps=0.0, angular_rps=0.0, battery_percent=86.0, voltage_v=24.8,
            battery_freshness=Freshness.FRESH, mode=RobotMode.IDLE, stop_latched=False,
            capabilities=["navigate", "camera"],
            sensors=[SensorStatus(name="camera", state=SensorState.OK, received_at=now)],
            trail=[{"x": 0.6, "y": 2.0}, {"x": 0.9, "y": 2.0}, {"x": 1.2, "y": 2.0}],
            path=[{"x": 1.2, "y": 2.0}, {"x": 1.5, "y": 2.2}, {"x": 1.8, "y": 2.4}],
            goal=Pose(x=1.8, y=2.4, yaw=0.4, frame_id="map"),
        )
        slave = RobotState(
            robot_id="robot_2", name=slave_config.name, role=slave_config.role,
            connection=Connection.OFFLINE if offline else Connection.ONLINE,
            received_at=None if offline else now,
            pose=None if offline else Pose(x=0.4, y=2.0, yaw=0.0, frame_id="map"),
            pose_freshness=Freshness.UNKNOWN if offline else Freshness.FRESH,
            linear_mps=None if offline else 0.0, angular_rps=None if offline else 0.0,
            battery_percent=None if offline else 79.0, voltage_v=None if offline else 24.5,
            battery_freshness=Freshness.UNKNOWN if offline else Freshness.FRESH,
            mode=RobotMode.UNKNOWN if offline else RobotMode.IDLE, stop_latched=None if offline else False,
            capabilities=["follow", "camera"],
            sensors=[SensorStatus(name="camera", state=SensorState.STALE if self._scenario is MockScenario.CAMERA_STALL else SensorState.OK, received_at=None if offline else now)],
            trail=[] if offline else [{"x": 0.0, "y": 2.0}, {"x": 0.2, "y": 2.0}, {"x": 0.4, "y": 2.0}],
            path=[] if offline else [{"x": 0.4, "y": 2.0}, {"x": 0.7, "y": 2.1}, {"x": 1.0, "y": 2.2}],
        )
        formation = FormationState(
            state=FormationMode.LOST if self._scenario is MockScenario.FOLLOW_LOST else FormationMode.UNPAIRED,
            master_id="robot_1", slave_id="robot_2", target_distance_m=0.8,
            distance_m=None if offline else 0.8, gap_error_m=None if offline else 0.0,
            bearing_rad=None if offline else 3.141592653589793,
            reason_code="MOCK_FOLLOW_LOST" if self._scenario is MockScenario.FOLLOW_LOST else None,
            received_at=now,
        )
        return StateSnapshot(robots=[master, slave], formation=formation, mode="mock", seq=self._sequence, server_time=now, map_id="mock_lab")

    def frame(self, robot_id: RobotId) -> CameraFrame | None:
        if robot_id == "robot_2" and self._scenario is MockScenario.CAMERA_STALL:
            return None
        now = datetime.now(UTC)
        role, color = (("MASTER", "#1769aa") if robot_id == "robot_1" else ("SLAVE", "#d97706"))
        image = Image.new("RGB", (640, 480), color)
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default()
        draw.rectangle((24, 24, 616, 456), outline="white", width=3)
        draw.text((45, 70), f"Pinky {role}", fill="white", font=font)
        draw.text((45, 105), robot_id, fill="white", font=font)
        draw.text((45, 140), now.isoformat(timespec="seconds"), fill="white", font=font)
        draw.ellipse((280, 225, 360, 305), fill="white")
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=82)
        return CameraFrame(robot_id=robot_id, frame_id=f"mock-{robot_id}-{self._sequence}", captured_at=now, received_at=now, width=640, height=480, jpeg=buffer.getvalue())

    def sensor_layers(self, robot_id: RobotId) -> dict[str, object]:
        """Small, explicit mock payload for the selected-robot map overlay.

        T12 will replace this with validated LaserScan/Costmap subscriptions;
        unsupported data remains a first-class state rather than fabricated data.
        """
        if robot_id == "robot_2":
            return {
                "robot_id": robot_id,
                "scan": {"state": "STALE" if self._scenario is MockScenario.SLAVE_OFFLINE else "UNSUPPORTED", "rays": []},
                "costmaps": [
                    {"name": "local_costmap", "state": "UNSUPPORTED", "cells": []},
                    {"name": "global_costmap", "state": "UNSUPPORTED", "cells": []},
                ],
            }
        return {
            "robot_id": robot_id,
            "scan": {"state": "OK", "rays": [{"angle_rad": angle, "range_m": distance} for angle, distance in ((-1.0, 1.4), (-.45, 2.0), (0.0, 1.1), (.45, 1.8), (1.0, 1.5))]},
            "costmaps": [
                {"name": "local_costmap", "state": "OK", "cells": [{"x": 1.8, "y": 2.0, "occupied": True}, {"x": 1.7, "y": 2.1, "occupied": True}]},
                {"name": "global_costmap", "state": "OK", "cells": [{"x": 2.2, "y": 2.5, "occupied": True}, {"x": 2.3, "y": 2.5, "occupied": True}]},
            ],
        }

    async def events(self) -> AsyncIterator[AdapterEvent]:
        while self._connected:
            snapshot = self.snapshot()
            while self._command_events:
                yield self._command_events.pop(0)
            for state in snapshot.robots:
                yield AdapterEvent(kind="robot_state", robot_id=state.robot_id, received_at=snapshot.server_time, payload=state.model_dump(mode="json"))
            yield AdapterEvent(kind="formation", received_at=snapshot.server_time, payload=snapshot.formation.model_dump(mode="json"))
            yield AdapterEvent(kind="map", received_at=snapshot.server_time, payload={"map_id": "mock_lab", "version": "1"})
            await asyncio.sleep(0.2)

    async def frames(self, robot_id: str) -> AsyncIterator[CameraFrame]:
        if robot_id not in {"robot_1", "robot_2"}:
            return
        while self._connected:
            frame = self.frame(robot_id)  # type: ignore[arg-type]
            if frame is not None:
                yield frame
            await asyncio.sleep(0.1)
