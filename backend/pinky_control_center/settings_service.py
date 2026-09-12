from __future__ import annotations

import asyncio

from pinky_control_center.map_service import MapService
from pinky_control_center.models import ActiveSettings, Connection, FormationMode, RobotMode, RobotState
from pinky_control_center.state_store import StateStore
from pinky_control_center.storage import Storage


class SettingsConflict(Exception):
    pass


class UnsafeSettingsChange(Exception):
    pass


class SettingsApplyFailed(Exception):
    pass


class SettingsService:
    """Persists configuration only after the mock adapter accepts its safe application."""

    def __init__(self, storage: Storage, adapter: object, maps: MapService, state_store: StateStore) -> None:
        self.storage = storage
        self.adapter = adapter
        self.maps = maps
        self.state_store = state_store
        self._update_lock = asyncio.Lock()

    def current(self) -> ActiveSettings:
        return self.storage.settings()

    @staticmethod
    def _moving(robot: RobotState) -> bool:
        return (
            robot.mode in {RobotMode.AUTO, RobotMode.FOLLOW, RobotMode.MANUAL}
            or (robot.linear_mps is not None and abs(robot.linear_mps) > 0.001)
            or (robot.angular_rps is not None and abs(robot.angular_rps) > 0.001)
        )

    def _can_change(self, changing_map: bool) -> bool:
        snapshot = self.state_store.snapshot()
        if any(self._moving(robot) for robot in snapshot.robots):
            return False
        if changing_map and (snapshot.formation.state not in {FormationMode.UNPAIRED, FormationMode.STOPPED} or snapshot.active_mission is not None):
            return False
        return True

    async def apply_current(self) -> None:
        """Apply the durable setting before any camera or command consumer starts."""
        apply = getattr(self.adapter, "apply_settings", None)
        if apply is None or not await apply(self.current().model_dump(mode="json", exclude={"version"})):
            raise SettingsApplyFailed()

    async def update(self, requested: ActiveSettings) -> ActiveSettings:
        # Serialize compare/apply/store so a losing version cannot leave the mock
        # adapter with values that differ from the durable active configuration.
        async with self._update_lock:
            current = self.current()
            if requested.version != current.version:
                raise SettingsConflict()
            if self.maps.metadata(requested.active_map_id) is None:
                raise ValueError("MAP_NOT_FOUND")
            if not self._can_change(requested.active_map_id != current.active_map_id):
                raise UnsafeSettingsChange()
            apply = getattr(self.adapter, "apply_settings", None)
            if apply is None or not await apply(requested.model_dump(mode="json", exclude={"version"})):
                raise SettingsApplyFailed()
            result = self.storage.update_settings(current.version, requested)
            if result is None:
                # Another process changed SQLite; its durable version wins.
                raise SettingsConflict()
            return result

    def initial_pose_allowed(self, robot_id: str) -> bool:
        snapshot = self.state_store.snapshot()
        robot = next((value for value in snapshot.robots if value.robot_id == robot_id), None)
        if robot is None or snapshot.active_mission is not None:
            return False
        return (
            robot.connection == Connection.ONLINE
            and robot.pose_freshness.value == "FRESH"
            and robot.tf_valid
            and robot.mode in {RobotMode.IDLE, RobotMode.STOPPED}
            and robot.stop_latched is False
            and robot.linear_mps is not None and abs(robot.linear_mps) <= 0.001
            and robot.angular_rps is not None and abs(robot.angular_rps) <= 0.001
            and snapshot.formation.state in {FormationMode.UNPAIRED, FormationMode.STOPPED}
        )
