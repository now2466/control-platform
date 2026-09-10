from __future__ import annotations

import math
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _finite(value: float | None) -> float | None:
    if value is not None and not math.isfinite(value):
        raise ValueError("must be a finite number")
    return value


FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]


class Connection(StrEnum):
    ONLINE = "ONLINE"
    STALE = "STALE"
    OFFLINE = "OFFLINE"


class Freshness(StrEnum):
    FRESH = "FRESH"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class Role(StrEnum):
    MASTER = "MASTER"
    SLAVE = "SLAVE"


class UserRole(StrEnum):
    VIEWER = "VIEWER"
    OPERATOR = "OPERATOR"
    ADMIN = "ADMIN"


class RobotMode(StrEnum):
    IDLE = "IDLE"
    AUTO = "AUTO"
    FOLLOW = "FOLLOW"
    MANUAL = "MANUAL"
    STOPPED = "STOPPED"
    ERROR = "ERROR"
    UNKNOWN = "UNKNOWN"


class SensorState(StrEnum):
    OK = "OK"
    STALE = "STALE"
    ERROR = "ERROR"
    UNSUPPORTED = "UNSUPPORTED"


class FormationMode(StrEnum):
    UNPAIRED = "UNPAIRED"
    READY = "READY"
    FOLLOWING = "FOLLOWING"
    PAUSED = "PAUSED"
    LOST = "LOST"
    REJOINING = "REJOINING"
    STOPPED = "STOPPED"
    ERROR = "ERROR"
    UNKNOWN = "UNKNOWN"


class CommandState(StrEnum):
    QUEUED = "QUEUED"
    ACCEPTED = "ACCEPTED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    CANCELED = "CANCELED"


class MissionState(StrEnum):
    DRAFT = "DRAFT"
    READY = "READY"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    PAUSING = "PAUSING"
    PAUSED = "PAUSED"
    CANCELING = "CANCELING"
    CANCELED = "CANCELED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class AlertSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class AlertState(StrEnum):
    ACTIVE = "ACTIVE"
    RESOLVED = "RESOLVED"


class Pose(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: FiniteFloat
    y: FiniteFloat
    yaw: FiniteFloat = Field(ge=-math.pi, le=math.pi)
    frame_id: str = Field(min_length=1, max_length=128)


class SensorStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=128)
    state: SensorState
    received_at: datetime | None = None


class RobotState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    robot_id: Literal["robot_1", "robot_2"]
    name: str = Field(min_length=1, max_length=128)
    role: Role
    connection: Connection
    received_at: datetime | None = None
    pose: Pose | None = None
    pose_freshness: Freshness
    linear_mps: float | None = Field(default=None, ge=-5, le=5)
    angular_rps: float | None = Field(default=None, ge=-10, le=10)
    battery_percent: float | None = Field(default=None, ge=0, le=100)
    voltage_v: float | None = Field(default=None, ge=0, le=100)
    battery_freshness: Freshness
    mode: RobotMode
    stop_latched: bool | None = None
    capabilities: list[str] = Field(default_factory=list)
    sensors: list[SensorStatus] = Field(default_factory=list)

    @field_validator("linear_mps", "angular_rps", "battery_percent", "voltage_v")
    @classmethod
    def finite_measurements(cls, value: float | None) -> float | None:
        return _finite(value)


class FormationState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: FormationMode
    master_id: Literal["robot_1", "robot_2"]
    slave_id: Literal["robot_1", "robot_2"]
    target_distance_m: float = Field(ge=0.5, le=2.0)
    distance_m: float | None = Field(default=None, ge=0)
    gap_error_m: float | None = None
    bearing_rad: float | None = Field(default=None, ge=-math.pi, le=math.pi)
    reason_code: str | None = Field(default=None, max_length=128)
    received_at: datetime | None = None

    @model_validator(mode="after")
    def separate_robots(self) -> "FormationState":
        if self.master_id == self.slave_id:
            raise ValueError("master_id and slave_id must be different")
        return self

    @field_validator("distance_m", "gap_error_m", "bearing_rad")
    @classmethod
    def finite_measurements(cls, value: float | None) -> float | None:
        return _finite(value)


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: UUID
    request_id: UUID
    target: str = Field(min_length=1, max_length=128)
    state: CommandState
    reason_code: str | None = Field(default=None, max_length=128)
    created_at: datetime
    updated_at: datetime


class Mission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mission_id: UUID
    name: str = Field(min_length=1, max_length=128)
    state: MissionState
    master_id: Literal["robot_1", "robot_2"]
    slave_id: Literal["robot_1", "robot_2"]
    map_id: str = Field(min_length=1, max_length=128)
    waypoints: list[Pose] = Field(min_length=1, max_length=100)
    repeat_count: int = Field(ge=1, le=100)
    waypoint_index: int = Field(ge=0)
    lap_index: int = Field(ge=0)
    progress_distance_m: float | None = Field(default=None, ge=0)
    failure_code: str | None = Field(default=None, max_length=128)
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def valid_robot_pair_and_waypoint_index(self) -> "Mission":
        if self.master_id == self.slave_id:
            raise ValueError("master_id and slave_id must be different")
        if self.waypoint_index >= len(self.waypoints):
            raise ValueError("waypoint_index must refer to a waypoint")
        return self

    @field_validator("progress_distance_m")
    @classmethod
    def finite_progress(cls, value: float | None) -> float | None:
        return _finite(value)


class Alert(BaseModel):
    model_config = ConfigDict(extra="forbid")
    alert_id: UUID
    code: str = Field(min_length=1, max_length=128)
    robot_id: Literal["robot_1", "robot_2"] | None = None
    mission_id: UUID | None = None
    severity: AlertSeverity
    state: AlertState
    acknowledged_at: datetime | None = None
    acknowledged_by: str | None = Field(default=None, max_length=128)
    first_seen_at: datetime
    last_seen_at: datetime
    occurrences: int = Field(ge=1)
    message: str = Field(min_length=1, max_length=1024)


class CommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: UUID
    robot_id: Literal["robot_1", "robot_2"]
    operation: str = Field(min_length=1, max_length=128)
    parameters: dict[str, object] = Field(default_factory=dict)


class CommandAcceptance(BaseModel):
    model_config = ConfigDict(extra="forbid")
    accepted: bool
    reason_code: str | None = Field(default=None, max_length=128)


class AdapterEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["robot_state", "formation", "command", "map", "path", "scan", "costmap"]
    robot_id: Literal["robot_1", "robot_2"] | None = None
    received_at: datetime
    payload: dict[str, object]


class CameraFrame(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)
    robot_id: Literal["robot_1", "robot_2"]
    frame_id: str = Field(min_length=1, max_length=128)
    captured_at: datetime | None = None
    received_at: datetime
    width: int = Field(ge=1, le=3840)
    height: int = Field(ge=1, le=2160)
    jpeg: bytes


class MockScenario(StrEnum):
    NORMAL = "normal"
    SLAVE_OFFLINE = "slave_offline"
    CAMERA_STALL = "camera_stall"
    FOLLOW_LOST = "follow_lost"
    COMMAND_REJECTED = "command_rejected"


class MockScenarioRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario: MockScenario


class ErrorBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    message: str
    details: dict[str, object] | None = None


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    error: ErrorBody
    request_id: UUID | None = None


class UserInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: UUID
    username: str
    role: UserRole


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=8, max_length=1024)


class LoginResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user: UserInfo
    csrf_token: str = Field(min_length=32)


class LeaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID


class ControlLease(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lease_id: UUID
    expires_at: datetime


class StateSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    robots: list[RobotState] = Field(min_length=2, max_length=2)
    formation: FormationState
    active_mission: None = None
    active_alerts: list[object] = Field(default_factory=list)
    mode: Literal["mock", "ros"]
    seq: int = Field(ge=0)
    server_time: datetime

    @model_validator(mode="after")
    def unique_robot_ids(self) -> "StateSnapshot":
        if len({robot.robot_id for robot in self.robots}) != len(self.robots):
            raise ValueError("robot IDs must be unique")
        return self
