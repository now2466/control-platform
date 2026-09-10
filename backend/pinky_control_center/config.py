from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

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
