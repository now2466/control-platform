from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from pinky_control_center.models import Connection, FormationState, Freshness, RobotState, StateSnapshot


class StateStore:
    """Normalizes adapter snapshots and marks each field stale independently."""

    def __init__(self, snapshot_source: Callable[[], StateSnapshot], clock: Callable[[], datetime] | None = None) -> None:
        self.snapshot_source = snapshot_source
        self.clock = clock or (lambda: datetime.now(UTC))
        self.sequence = 0
        self.disconnected: set[str] = set()
        self.formation_override: FormationState | None = None
        self.active_mission: object | None = None

    def disconnect(self, robot_id: str) -> None:
        self.disconnected.add(robot_id)

    def snapshot(self) -> StateSnapshot:
        now = self.clock()
        source = self.snapshot_source()
        robots = [self._offline(robot) if robot.robot_id in self.disconnected else self._fresh_robot(robot, now) for robot in source.robots]
        formation = self.formation_override or source.formation
        if any(not robot.tf_valid or robot.pose is None for robot in robots):
            formation = formation.model_copy(update={"distance_m": None, "gap_error_m": None, "bearing_rad": None})
        self.sequence += 1
        return source.model_copy(update={"robots": robots, "formation": formation, "active_mission": self.active_mission, "seq": self.sequence, "server_time": now})

    @staticmethod
    def _offline(robot: RobotState) -> RobotState:
        return robot.model_copy(update={"connection": Connection.OFFLINE, "pose_freshness": Freshness.UNKNOWN, "battery_freshness": Freshness.UNKNOWN, "tf_valid": False, "tf_reason_code": "SAFETY_DISCONNECTED"})

    @staticmethod
    def _fresh_robot(robot: RobotState, now: datetime) -> RobotState:
        if robot.received_at is None:
            return robot.model_copy(update={"connection": Connection.OFFLINE, "pose_freshness": Freshness.UNKNOWN, "battery_freshness": Freshness.UNKNOWN, "tf_valid": False, "tf_reason_code": "TF_UNAVAILABLE"})
        age = now - robot.received_at.astimezone(UTC)
        connection = Connection.OFFLINE if age > timedelta(seconds=3) else Connection.STALE if age > timedelta(seconds=1) else robot.connection
        pose_freshness = Freshness.STALE if age > timedelta(seconds=1) else robot.pose_freshness
        battery_freshness = Freshness.STALE if age > timedelta(seconds=15) else robot.battery_freshness
        return robot.model_copy(update={"connection": connection, "pose_freshness": pose_freshness, "battery_freshness": battery_freshness})
