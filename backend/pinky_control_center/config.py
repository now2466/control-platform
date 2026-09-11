from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from pinky_control_center.models import Role


class RobotConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    robot_id: Literal["robot_1", "robot_2"]
    name: str = Field(min_length=1, max_length=128)
    role: Role
    namespace: str = Field(pattern=r"^/[A-Za-z0-9_/]+$")


class MockConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    robots: list[RobotConfig] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def unique_robot_ids_and_namespaces(self) -> "MockConfig":
        if len({robot.robot_id for robot in self.robots}) != len(self.robots):
            raise ValueError("robot IDs must be unique")
        if len({robot.namespace for robot in self.robots}) != len(self.robots):
            raise ValueError("robot namespaces must be unique")
        if {robot.role for robot in self.robots} != {Role.MASTER, Role.SLAVE}:
            raise ValueError("exactly one MASTER and one SLAVE are required")
        return self


def load_mock_config(path: Path | None = None) -> MockConfig:
    if path is None:
        contents = resources.files("pinky_control_center").joinpath(
            "resources", "config", "robots.mock.yaml"
        ).read_text(encoding="utf-8")
    else:
        contents = path.read_text(encoding="utf-8")
    data = yaml.safe_load(contents)
    return MockConfig.model_validate(data)


class RosbridgeTopics(BaseModel):
    """ROS names are deployment data, never editable through the dashboard."""

    model_config = ConfigDict(extra="forbid")
    odom: str = Field(pattern=r"^/")
    battery_percent: str = Field(pattern=r"^/")
    battery_voltage: str = Field(pattern=r"^/")
    camera_compressed: str = Field(pattern=r"^/")
    control_status: str = Field(pattern=r"^/")
    path: str | None = Field(default=None, pattern=r"^/")
    manual_velocity: str | None = Field(default=None, pattern=r"^/")
    initial_pose: str | None = Field(default=None, pattern=r"^/")


class RosbridgeServices(BaseModel):
    model_config = ConfigDict(extra="forbid")
    control_command: str = Field(pattern=r"^/")
    control_command_type: str = Field(min_length=1)
    control_available: bool = False
    follow_command: str | None = Field(default=None, pattern=r"^/")
    follow_command_type: str | None = None
    follow_available: bool = False


class RosbridgeCameraOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    throttle_rate_ms: int = Field(default=100, ge=1, le=60_000)
    fragment_size: int = Field(default=65_536, ge=1024, le=1_000_000)


class RosbridgeSecurityConfig(BaseModel):
    """Names of deployment environment variables; never credential values."""

    model_config = ConfigDict(extra="forbid")
    verify_tls: bool = True
    ca_cert_env: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]*$")
    client_cert_env: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]*$")
    client_key_env: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]*$")
    authorization_token_env: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]*$")

    @model_validator(mode="after")
    def paired_client_certificate(self) -> "RosbridgeSecurityConfig":
        if bool(self.client_cert_env) != bool(self.client_key_env):
            raise ValueError("client_cert_env and client_key_env must be configured together")
        return self


class RosbridgeRobotConfig(RobotConfig):
    domain_id: int
    bridge_url: str
    topics: RosbridgeTopics
    services: RosbridgeServices
    camera: RosbridgeCameraOptions = Field(default_factory=RosbridgeCameraOptions)
    security: RosbridgeSecurityConfig = Field(default_factory=RosbridgeSecurityConfig)

    @field_validator("bridge_url")
    @classmethod
    def websocket_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"ws", "wss"} or not parsed.netloc:
            raise ValueError("bridge_url must be a ws:// or wss:// URL")
        return value

    @model_validator(mode="after")
    def secure_transport_matches_url(self) -> "RosbridgeRobotConfig":
        if urlparse(self.bridge_url).scheme != "wss" and (
            self.security.ca_cert_env or self.security.client_cert_env or self.security.authorization_token_env
        ):
            raise ValueError("TLS or authorization environment mappings require a wss:// bridge_url")
        return self


class RosbridgeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    robots: list[RosbridgeRobotConfig] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def fixed_deployment_contract(self) -> "RosbridgeConfig":
        by_id = {robot.robot_id: robot for robot in self.robots}
        if set(by_id) != {"robot_1", "robot_2"}:
            raise ValueError("ROS config must contain robot_1 and robot_2")
        if by_id["robot_1"].domain_id != 12 or by_id["robot_2"].domain_id != 13:
            raise ValueError("robot_1 domain_id must be 12 and robot_2 domain_id must be 13")
        if len({robot.namespace for robot in self.robots}) != 2:
            raise ValueError("robot namespaces must be unique")
        if len({robot.bridge_url for robot in self.robots}) != 2:
            raise ValueError("each robot must use a separate rosbridge endpoint")
        if {robot.role for robot in self.robots} != {Role.MASTER, Role.SLAVE}:
            raise ValueError("exactly one MASTER and one SLAVE are required")
        slave = by_id["robot_2"]
        if not slave.services.follow_command or not slave.services.follow_command_type:
            raise ValueError("robot_2 requires a follow command service mapping")
        for robot in self.robots:
            endpoints = [
                robot.topics.odom, robot.topics.battery_percent, robot.topics.battery_voltage,
                robot.topics.camera_compressed, robot.topics.control_status, robot.topics.path,
                robot.topics.manual_velocity, robot.topics.initial_pose, robot.services.control_command,
                robot.services.follow_command,
            ]
            if any(endpoint is not None and not endpoint.startswith(robot.namespace + "/") for endpoint in endpoints):
                raise ValueError(f"all {robot.robot_id} ROS mappings must stay under {robot.namespace}")
        return self


def load_ros_config(path: Path | None = None) -> RosbridgeConfig:
    if path is None:
        contents = resources.files("pinky_control_center").joinpath(
            "resources", "config", "robots.ros.yaml"
        ).read_text(encoding="utf-8")
    else:
        contents = path.read_text(encoding="utf-8")
    return RosbridgeConfig.model_validate(yaml.safe_load(contents))
