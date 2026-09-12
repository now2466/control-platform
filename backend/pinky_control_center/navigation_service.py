from __future__ import annotations

from uuid import UUID, uuid4

from pinky_control_center.map_service import MapService
from pinky_control_center.models import (
    CommandRequest,
    Connection,
    FormationMode,
    LocalizationResetRequest,
    MapNavigationRequest,
    Pose,
    RobotMode,
    UserInfo,
)
from pinky_control_center.state_store import StateStore
from pinky_control_center.storage import Storage


class NavigationConflict(Exception):
    """A map navigation request is not safe to accept in the current state."""


class NavigationService:
    """Validate and execute a guarded single-robot map navigation request."""

    def __init__(self, storage: Storage, adapter: object, state_store: StateStore, maps: MapService, settings_provider) -> None:
        self.storage = storage
        self.adapter = adapter
        self.state_store = state_store
        self.maps = maps
        self.settings_provider = settings_provider

    @staticmethod
    def _still(robot) -> bool:
        return (
            robot.linear_mps is not None
            and abs(robot.linear_mps) <= 0.001
            and robot.angular_rps is not None
            and abs(robot.angular_rps) <= 0.001
        )

    def _validate(self, robot_id: str, payload: MapNavigationRequest) -> None:
        settings = self.settings_provider()
        metadata = self.maps.metadata(payload.map_id)
        if metadata is None:
            raise NavigationConflict("MAP_NOT_FOUND")
        if settings.active_map_id != payload.map_id:
            raise NavigationConflict("MAP_NOT_ACTIVE")
        if payload.start_pose.frame_id != metadata.frame_id or payload.goal.frame_id != metadata.frame_id:
            raise NavigationConflict("MAP_FRAME_MISMATCH")
        if not self.maps.is_free(payload.map_id, payload.start_pose.x, payload.start_pose.y) or not self.maps.is_free(payload.map_id, payload.goal.x, payload.goal.y):
            raise NavigationConflict("MAP_POINT_BLOCKED")

        snapshot = self.state_store.snapshot()
        robot = next((item for item in snapshot.robots if item.robot_id == robot_id), None)
        if robot is None:
            raise NavigationConflict("ROBOT_NOT_FOUND")
        if robot.connection is not Connection.ONLINE or robot.pose is None or robot.pose_freshness.value != "FRESH":
            raise NavigationConflict("ROBOT_NOT_READY")
        if not robot.tf_valid:
            raise NavigationConflict("MAP_TF_UNVERIFIED")
        if "navigate" not in robot.capabilities:
            raise NavigationConflict("NAVIGATION_UNAVAILABLE")
        if robot.stop_latched is not False:
            raise NavigationConflict("STOP_LATCHED")
        if robot.mode is not RobotMode.IDLE:
            raise NavigationConflict("ROBOT_NOT_IDLE")
        if not self._still(robot):
            raise NavigationConflict("ROBOT_MOVING")
        if snapshot.active_mission is not None:
            raise NavigationConflict("MISSION_ACTIVE")
        if snapshot.formation.state not in {FormationMode.UNPAIRED, FormationMode.STOPPED}:
            raise NavigationConflict("FORMATION_BUSY")

    def _validate_localization_reset(self, robot_id: str, payload: LocalizationResetRequest) -> None:
        metadata = self.maps.metadata(payload.map_id)
        if metadata is None:
            raise NavigationConflict("MAP_NOT_FOUND")
        if self.settings_provider().active_map_id != payload.map_id:
            raise NavigationConflict("MAP_NOT_ACTIVE")
        if payload.pose.frame_id != metadata.frame_id:
            raise NavigationConflict("MAP_FRAME_MISMATCH")
        if not self.maps.is_free(payload.map_id, payload.pose.x, payload.pose.y):
            raise NavigationConflict("MAP_POINT_BLOCKED")
        snapshot = self.state_store.snapshot()
        robot = next((item for item in snapshot.robots if item.robot_id == robot_id), None)
        if robot is None:
            raise NavigationConflict("ROBOT_NOT_FOUND")
        if robot.connection is not Connection.ONLINE or robot.pose is None or robot.pose_freshness.value != "FRESH":
            raise NavigationConflict("ROBOT_NOT_READY")
        if robot.mode not in {RobotMode.IDLE, RobotMode.STOPPED}:
            raise NavigationConflict("ROBOT_NOT_STOPPED")
        if not self._still(robot):
            raise NavigationConflict("ROBOT_MOVING")
        if snapshot.active_mission is not None:
            raise NavigationConflict("MISSION_ACTIVE")
        if snapshot.formation.state not in {FormationMode.UNPAIRED, FormationMode.STOPPED}:
            raise NavigationConflict("FORMATION_BUSY")

    def start(self, user: UserInfo, robot_id: str, payload: MapNavigationRequest, dispatcher) -> dict[str, object]:
        self._validate(robot_id, payload)
        # Reusing the request UUID as the navigation identity preserves the
        # command idempotency contract when a browser retries the same request.
        navigation_id = str(payload.request_id)
        parameters = {
            "robot_id": robot_id,
            "map_id": payload.map_id,
            "start_pose": payload.start_pose.model_dump(mode="json"),
            "goal": payload.goal.model_dump(mode="json"),
            "navigation_id": navigation_id,
        }
        result = dispatcher.submit(
            user,
            payload.request_id,
            robot_id,
            "navigate_from_map",
            parameters=parameters,
        )
        self.storage.record_history_safe(
            event_type="NAVIGATION_REQUESTED",
            user=user,
            robot_id=robot_id,
            payload={
                "command_id": result["command_id"],
                "navigation_id": navigation_id,
                "map_id": payload.map_id,
                "goal": payload.goal.model_dump(mode="json"),
            },
            dedupe_key=f"navigation:{result['command_id']}:requested",
        )
        return {**result, "navigation_id": navigation_id}

    def reset_localization(self, user: UserInfo, robot_id: str, payload: LocalizationResetRequest, dispatcher) -> dict[str, object]:
        self._validate_localization_reset(robot_id, payload)
        parameters = {"pose": payload.pose.model_dump(mode="json"), "map_id": payload.map_id}
        result = dispatcher.submit(user, payload.request_id, robot_id, "initial_pose", parameters=parameters)
        self.storage.record_history_safe(
            event_type="LOCALIZATION_RESET_REQUESTED",
            user=user,
            robot_id=robot_id,
            payload={"command_id": result["command_id"], "map_id": payload.map_id, "pose": parameters["pose"]},
            dedupe_key=f"localization-reset:{result['command_id']}:requested",
        )
        return result

    async def execute(self, _operation: str, parameters: dict[str, object]) -> tuple[bool, dict[str, object]]:
        robot_id = str(parameters.get("robot_id"))
        try:
            start_pose = Pose.model_validate(parameters["start_pose"])
            goal = Pose.model_validate(parameters["goal"])
        except (KeyError, TypeError, ValueError):
            return False, {"reason_code": "INVALID_VALUE"}

        async def send(operation: str, values: dict[str, object]) -> bool:
            result = await self.adapter.execute(
                CommandRequest(command_id=uuid4(), robot_id=robot_id, operation=operation, parameters=values)
            )
            return result.accepted

        if not await send("initial_pose", {"pose": start_pose.model_dump(mode="json")}):
            return False, {"reason_code": "INITIAL_POSE_REJECTED"}
        if not await send("set_mode", {"mode": RobotMode.AUTO.value}):
            return False, {"reason_code": "AUTO_MODE_REJECTED"}

        navigation_id = str(parameters.get("navigation_id") or uuid4())
        try:
            navigation_command_id = UUID(navigation_id)
        except ValueError:
            navigation_command_id = uuid4()
        accepted = await self.adapter.execute(
            CommandRequest(
                command_id=navigation_command_id,
                robot_id=robot_id,
                operation="navigate",
                parameters={
                    "map_id": str(parameters.get("map_id", "")),
                    "goal": goal.model_dump(mode="json"),
                    "navigation_id": navigation_id,
                },
            )
        )
        if not accepted.accepted:
            try:
                await self.adapter.execute(
                    CommandRequest(command_id=uuid4(), robot_id=robot_id, operation="stop", parameters={"reason": "NAVIGATION_REJECTED"})
                )
            except Exception:
                pass
            return False, {"reason_code": accepted.reason_code or "NAVIGATION_REJECTED"}
        return True, {
            "navigation_id": navigation_id,
            "robot_id": robot_id,
            "map_id": parameters.get("map_id"),
            "goal": goal.model_dump(mode="json"),
            # Do not use the reserved top-level `state` key here: Storage
            # merges command results into the command response, where state
            # is the durable dispatcher state.
            "navigation_state": "REQUESTED",
        }
