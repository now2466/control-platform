from __future__ import annotations

from uuid import UUID, uuid4
import threading

from fastapi import HTTPException

from pinky_control_center.models import Connection, FormationMode, FormationState, Freshness, MissionState, Pose, UserInfo


class MissionService:
    """T06 orchestration. Adapter calls are deliberately ordered here, before ROS actions exist."""
    def __init__(self, storage, adapter, state_store, clock) -> None:
        self.storage, self.adapter, self.state_store, self.clock = storage, adapter, state_store, clock
        self.active_id: str | None = None
        self.slave_wait_deadline: float | None = None
        self.formation_pause_pending: tuple[str, str] | None = None
        self.formation_pause_reason: str | None = None
        self._tick_lock = threading.Lock()
        # Recovery never resumes motion. Persisted in-flight missions need operator action.
        import json
        for row in self.storage.connection.execute("SELECT id,payload_json FROM missions WHERE state IN ('STARTING','RUNNING','PAUSING','CANCELING')"):
            payload = json.loads(row["payload_json"])
            payload["state"] = "PAUSED"; payload["failure_code"] = "SERVER_RESTART"
            self.storage.update_mission(row["id"], payload)

    def master_navigation_succeeded(self, mission_id: str) -> None:
        """Adapter result hook: master success is not mission success until the slave is settled."""
        if mission_id == self.active_id and self.slave_wait_deadline is None:
            self.slave_wait_deadline = self.clock() + 10.0

    async def protective_pause(self, reason: str) -> None:
        """Pause an active formation once for an alert that invalidates safe motion."""
        current = self.formation()
        if current.state not in {FormationMode.FOLLOWING, FormationMode.LOST, FormationMode.PAUSING} and self.active_id is None:
            return
        if self.formation_pause_pending is not None:
            return
        master, slave = current.master_id, current.slave_id
        if self.active_id:
            row = self.storage.connection.execute("SELECT payload_json FROM missions WHERE id=?", (self.active_id,)).fetchone()
            if row:
                import json
                mission = json.loads(row["payload_json"])
                if mission["state"] in {"RUNNING", "STARTING"}:
                    mission["state"] = "PAUSING"
                    mission["failure_code"] = reason
                    self.storage.update_mission(self.active_id, mission)
        self._set_formation(FormationMode.LOST if reason == "FOLLOW_LOST" else FormationMode.PAUSING, reason)
        for robot_id in (master, slave):
            try:
                await self.adapter.execute(__import__('pinky_control_center.models', fromlist=['CommandRequest']).CommandRequest(command_id=uuid4(), robot_id=robot_id, operation="stop", parameters={"reason": reason}))
            except Exception:
                pass
        self.formation_pause_pending = (master, slave)
        self.formation_pause_reason = reason

    def consume_adapter_event(self, event) -> None:
        """Small adapter-result boundary shared by mock now and ROS event ingestion later."""
        if event.kind != "command" or event.robot_id != "robot_1" or event.payload.get("operation") != "navigate":
            return
        mission_id = event.payload.get("parameters", {}).get("mission_id")
        if event.payload.get("state") == "SUCCEEDED" and isinstance(mission_id, str):
            self.master_navigation_succeeded(mission_id)

    def formation(self) -> FormationState:
        value = self.state_store.formation_override
        if value is None:
            source = self.state_store.snapshot_source().formation
            self.state_store.formation_override = source
            value = source
        return value

    def _set_formation(self, state: FormationMode, reason: str | None = None) -> None:
        current = self.formation()
        self.state_store.formation_override = current.model_copy(update={"state": state, "reason_code": reason})

    async def tick(self) -> None:
        if not self._tick_lock.acquire(blocking=False):
            return
        try:
            await self._tick()
        finally:
            self._tick_lock.release()

    async def _tick(self) -> None:
        """Complete transitional states only from fresh stop observations."""
        if self.formation_pause_pending:
            master, slave = self.formation_pause_pending
            robots = {robot.robot_id: robot for robot in self.state_store.snapshot().robots}
            if all(robots[robot_id].stop_latched and robots[robot_id].pose_freshness == Freshness.FRESH and abs(robots[robot_id].linear_mps or 0) < .01 and abs(robots[robot_id].angular_rps or 0) < .02 for robot_id in (master, slave)):
                if self.formation_pause_reason == "FOLLOW_LOST":
                    self._set_formation(FormationMode.LOST, "FOLLOW_LOST")
                else:
                    self._set_formation(FormationMode.PAUSED, self.formation_pause_reason)
                self.formation_pause_pending = None
                self.formation_pause_reason = None
        if not self.active_id:
            return
        mission_id = self.active_id
        row = self.storage.connection.execute("SELECT payload_json FROM missions WHERE id=?", (mission_id,)).fetchone()
        if not row:
            return
        import json
        mission = json.loads(row["payload_json"])
        if mission["state"] == "RUNNING":
            master = next(robot for robot in self.state_store.snapshot().robots if robot.robot_id == mission["master_id"])
            goal = mission["waypoints"][mission["waypoint_index"]]
            if master.pose is not None:
                import math
                mission["progress_distance_m"] = math.hypot(goal["x"] - master.pose.x, goal["y"] - master.pose.y)
                self.storage.update_mission(mission_id, mission)
        if self.slave_wait_deadline is not None and mission["state"] == "RUNNING":
            robots = {robot.robot_id: robot for robot in self.state_store.snapshot().robots}
            slave = robots[mission["slave_id"]]
            formation = self.formation()
            settled = slave.stop_latched and slave.pose_freshness == Freshness.FRESH and abs(slave.linear_mps or 0) < .01 and abs(slave.angular_rps or 0) < .02 and formation.distance_m is not None and abs(formation.distance_m - formation.target_distance_m) <= .2
            if settled:
                # Mark this completion consumed before awaiting the next adapter call.
                self.slave_wait_deadline = float("inf")
                if mission["waypoint_index"] + 1 < len(mission["waypoints"]):
                    mission["waypoint_index"] += 1
                    await self._navigate(mission, mission_id)
                elif mission["lap_index"] + 1 < mission["repeat_count"]:
                    mission["lap_index"] += 1; mission["waypoint_index"] = 0
                    await self._navigate(mission, mission_id)
                else:
                    mission["state"] = "SUCCEEDED"; self.active_id = None; self._set_formation(FormationMode.READY)
                self.storage.update_mission(mission_id, mission)
                if mission["state"] == "RUNNING": self.slave_wait_deadline = None
                return
        if self.slave_wait_deadline is not None and self.clock() >= self.slave_wait_deadline and mission["state"] == "RUNNING":
            mission["state"] = "PAUSED"; mission["failure_code"] = "SLAVE_SETTLE_TIMEOUT"
            self._set_formation(FormationMode.PAUSED, "SLAVE_SETTLE_TIMEOUT")
            self.slave_wait_deadline = None
            self.storage.update_mission(self.active_id, mission)
            return
        source = self.state_store.snapshot_source()
        source_formation = source.formation
        if source_formation.state == FormationMode.LOST and self.formation_pause_pending is None and mission["state"] in {"RUNNING", "STARTING"}:
            mission["state"] = "PAUSING"; mission["failure_code"] = "FOLLOW_LOST"
            self._set_formation(FormationMode.LOST, "FOLLOW_LOST")
            for robot_id in ("robot_1", "robot_2"):
                await self.adapter.execute(__import__('pinky_control_center.models', fromlist=['CommandRequest']).CommandRequest(command_id=uuid4(), robot_id=robot_id, operation="stop", parameters={"reason":"FOLLOW_LOST"}))
            self.storage.update_mission(self.active_id, mission)
            return
        if mission["state"] in {"PAUSING", "CANCELING"}:
            robots = {robot.robot_id: robot for robot in self.state_store.snapshot().robots}
            if all(robots[robot_id].stop_latched and robots[robot_id].pose_freshness == Freshness.FRESH and abs(robots[robot_id].linear_mps or 0) < .01 and abs(robots[robot_id].angular_rps or 0) < .02 for robot_id in (mission["master_id"], mission["slave_id"])):
                canceled = mission["state"] == "CANCELING"
                mission["state"] = "CANCELED" if canceled else "PAUSED"
                if self.formation().state != FormationMode.LOST: self._set_formation(FormationMode.READY if canceled else FormationMode.PAUSED)
                mission_id = self.active_id
                self.storage.update_mission(mission_id, mission)
                if canceled: self.active_id = None

    def pair_allowed(self, master: str, slave: str) -> None:
        snapshot = self.state_store.snapshot()
        robots = {r.robot_id: r for r in snapshot.robots}
        if master == slave or master not in robots or slave not in robots:
            raise HTTPException(422, detail="INVALID_VALUE")
        if any(robots[x].connection != Connection.ONLINE or robots[x].stop_latched for x in (master, slave)):
            raise HTTPException(409, detail="INVALID_STATE")
        if any(robots[x].pose is None or not robots[x].tf_valid for x in (master, slave)):
            raise HTTPException(409, detail="INVALID_STATE")
        if "navigate" not in robots[master].capabilities or "follow" not in robots[slave].capabilities:
            raise HTTPException(409, detail="INVALID_STATE")

    def rejoin_allowed(self, master: str, slave: str) -> None:
        self.pair_allowed(master, slave)
        robots = {robot.robot_id: robot for robot in self.state_store.snapshot().robots}
        if not robots[slave].path:
            raise HTTPException(409, detail="INVALID_STATE")

    def formation_action(self, user: UserInfo, request_id: UUID, action: str, master: str, slave: str, dispatcher):
        current = self.formation()
        if action == "pair":
            if current.state not in {FormationMode.UNPAIRED, FormationMode.STOPPED}:
                raise HTTPException(409, detail="INVALID_STATE")
            self.pair_allowed(master, slave)
        elif action == "unpair" and current.state not in {FormationMode.READY, FormationMode.PAUSED, FormationMode.STOPPED}:
            raise HTTPException(409, detail="INVALID_STATE")
        elif action == "rejoin" and current.state != FormationMode.LOST:
            raise HTTPException(409, detail="INVALID_STATE")
        elif action == "rejoin":
            self.rejoin_allowed(master, slave)
        elif action == "pause" and current.state != FormationMode.FOLLOWING:
            raise HTTPException(409, detail="INVALID_STATE")
        return dispatcher.submit(user, request_id, "all", "formation_" + action, parameters={"master_id": master, "slave_id": slave})

    async def execute_formation(self, operation: str, parameters: dict[str, object]) -> tuple[bool, dict[str, object]]:
        action = operation.removeprefix("formation_")
        master, slave = str(parameters.get("master_id", "robot_1")), str(parameters.get("slave_id", "robot_2"))
        if action == "pair":
            self.state_store.formation_override = FormationState(state=FormationMode.READY, master_id=master, slave_id=slave, target_distance_m=.8, distance_m=.8, gap_error_m=0.)
        elif action == "unpair": self._set_formation(FormationMode.UNPAIRED)
        elif action == "pause":
            from pinky_control_center.models import CommandRequest
            self._set_formation(FormationMode.PAUSING)
            try:
                calls = ((master, "cancel_navigation"), (master, "stop"), (slave, "stop"))
                results = [await self.adapter.execute(CommandRequest(command_id=uuid4(), robot_id=robot_id, operation=op, parameters={"reason": "FORMATION_PAUSE"})) for robot_id, op in calls]
            except Exception:
                self._set_formation(FormationMode.ERROR, "STOP_UNCONFIRMED")
                return False, {"reason_code": "STOP_UNCONFIRMED"}
            if not all(result.accepted for result in results):
                self._set_formation(FormationMode.ERROR, "STOP_UNCONFIRMED")
                return False, {"reason_code": "STOP_UNCONFIRMED"}
            self.formation_pause_pending = (master, slave)
            self.formation_pause_reason = None
        elif action == "rejoin":
            self._set_formation(FormationMode.REJOINING)
            from pinky_control_center.models import CommandRequest
            try:
                stops = [await self.adapter.execute(CommandRequest(command_id=uuid4(), robot_id=robot_id, operation="stop", parameters={"reason": "REJOIN"})) for robot_id in (master, slave)]
                rejoin = await self.adapter.execute(CommandRequest(command_id=uuid4(), robot_id=slave, operation="rejoin", parameters={"master_id": master})) if all(stop.accepted for stop in stops) else next(stop for stop in stops if not stop.accepted)
            except Exception:
                self._set_formation(FormationMode.ERROR, "REJOIN_FAILED")
                return False, {"reason_code": "REJOIN_FAILED"}
            if not rejoin.accepted:
                self._set_formation(FormationMode.ERROR, rejoin.reason_code or "REJOIN_FAILED")
                return False, {"reason_code": rejoin.reason_code or "REJOIN_FAILED"}
            self._set_formation(FormationMode.READY)
        return True, {"targets": [{"robot_id": master, "state": "ACKNOWLEDGED"}, {"robot_id": slave, "state": "ACKNOWLEDGED"}]}

    def create(self, user: UserInfo, payload: dict[str, object]) -> dict[str, object]:
        waypoints = payload.get("waypoints")
        if not isinstance(waypoints, list) or not 1 <= len(waypoints) <= 100:
            raise HTTPException(422, detail="INVALID_VALUE")
        try:
            for waypoint in waypoints:
                Pose.model_validate(waypoint)
        except Exception as error: raise HTTPException(422, detail="INVALID_VALUE") from error
        data = {"name": payload.get("name"), "state": MissionState.DRAFT.value, "master_id": self.formation().master_id, "slave_id": self.formation().slave_id, "map_id": payload.get("map_id"), "waypoints": waypoints, "repeat_count": payload.get("repeat_count", 1), "waypoint_index": 0, "lap_index": 0, "progress_distance_m": None, "failure_code": None, "version": 1}
        if not isinstance(data["name"], str) or not isinstance(data["map_id"], str) or data["map_id"] != "mock_lab" or not isinstance(data["repeat_count"], int) or not 1 <= data["repeat_count"] <= 100: raise HTTPException(422, detail="INVALID_VALUE")
        return self.storage.create_mission_idempotent(user, UUID(str(payload["request_id"])), data)

    def edit(self, user: UserInfo, mission_id: str, payload: dict[str, object]) -> dict[str, object]:
        with self.storage._command_lock:
            return self._edit_locked(user, mission_id, payload)

    def _edit_locked(self, user: UserInfo, mission_id: str, payload: dict[str, object]) -> dict[str, object]:
        request_id = UUID(str(payload["request_id"])); command = self.storage.create_command(user, request_id, mission_id, {"operation": "mission_edit", "mission_id": mission_id, "payload": {key: value for key, value in payload.items() if key not in {"request_id", "lease_id"}}}); existing = command.get("result", {}).get("mission") if isinstance(command.get("result"), dict) else None
        if existing: return existing
        mission = self.storage.mission(mission_id, user)
        if mission is None: raise HTTPException(404, detail="MISSION_NOT_FOUND")
        if mission["state"] not in {"DRAFT", "READY"} or payload.get("version") != mission.get("version"):
            raise HTTPException(409, detail="STALE_VERSION" if payload.get("version") != mission.get("version") else "INVALID_STATE")
        for field in ("name", "waypoints", "repeat_count"):
            if field in payload: mission[field] = payload[field]
        if not isinstance(mission["name"], str) or not 1 <= len(mission["name"].strip()) <= 128:
            raise HTTPException(422, detail="INVALID_VALUE")
        if not isinstance(mission["waypoints"], list) or not 1 <= len(mission["waypoints"]) <= 100 or not isinstance(mission["repeat_count"], int) or not 1 <= mission["repeat_count"] <= 100:
            raise HTTPException(422, detail="INVALID_VALUE")
        try:
            for waypoint in mission["waypoints"]: Pose.model_validate(waypoint)
        except Exception as error: raise HTTPException(422, detail="INVALID_VALUE") from error
        if mission["state"] == "READY": mission["state"] = "DRAFT"
        mission["version"] += 1; self.storage.update_mission(mission_id, mission)
        self.storage.set_command_result(str(command["command_id"]), {"mission": mission}); self.storage.set_command_state(str(command["command_id"]), "SUCCEEDED")
        return mission

    async def _navigate(self, mission: dict[str, object], mission_id: str) -> None:
        from pinky_control_center.models import CommandRequest
        accepted = await self.adapter.execute(CommandRequest(command_id=uuid4(), robot_id=mission["master_id"], operation="navigate", parameters={"goal": mission["waypoints"][mission["waypoint_index"]], "mission_id": mission_id}))
        if not accepted.accepted:
            for robot_id in (mission["master_id"], mission["slave_id"]):
                try: await self.adapter.execute(CommandRequest(command_id=uuid4(), robot_id=robot_id, operation="stop", parameters={"reason":"NAVIGATION_REJECTED"}))
                except Exception: pass
            mission["state"] = "FAILED"; mission["failure_code"] = "NAVIGATION_REJECTED"; self.active_id = None

    def action(self, user: UserInfo, mission_id: str, request_id: UUID, action: str, dispatcher):
        mission = self.storage.mission(mission_id, user)
        if mission is None: raise HTTPException(404, detail="MISSION_NOT_FOUND")
        state = mission["state"]
        valid = {"validate": {"DRAFT"}, "start": {"READY", "PAUSED"}, "pause": {"RUNNING"}, "resume": {"PAUSED"}, "cancel": {"DRAFT", "READY", "RUNNING", "PAUSED"}}
        if action not in valid or state not in valid[action]: raise HTTPException(409, detail="INVALID_STATE")
        if action in {"start", "resume"} and self.formation().state not in {FormationMode.READY, FormationMode.PAUSED}: raise HTTPException(409, detail="INVALID_STATE")
        result = dispatcher.submit(user, request_id, mission_id, "mission_" + action, parameters={"mission_id": mission_id})
        # Claim a start synchronously: distinct concurrent requests cannot enqueue two goals.
        if action in {"start", "resume"} and result.get("state") == "ACCEPTED":
            mission["state"] = "STARTING"; self.storage.update_mission(mission_id, mission)
        return result

    async def execute_mission(self, operation: str, parameters: dict[str, object], user: UserInfo | None = None) -> tuple[bool, dict[str, object]]:
        mission_id = str(parameters["mission_id"])
        row = self.storage.connection.execute("SELECT payload_json FROM missions WHERE id=?", (mission_id,)).fetchone()
        if not row: return False, {"reason_code": "MISSION_NOT_FOUND"}
        import json
        mission = json.loads(row["payload_json"]); action = operation.removeprefix("mission_")
        if action == "validate": mission["state"] = "READY"
        elif action in {"start", "resume"}:
            mission["state"] = "STARTING"; slave, master = mission["slave_id"], mission["master_id"]
            calls = [(slave, "follow_ready", {}), (slave, "follow_start", {})]
            for robot_id, op, params in calls:
                accepted = await self.adapter.execute(__import__('pinky_control_center.models', fromlist=['CommandRequest']).CommandRequest(command_id=uuid4(), robot_id=robot_id, operation=op, parameters=params))
                if not accepted.accepted:
                    for target in ("robot_1", "robot_2"):
                        try: await self.adapter.execute(__import__('pinky_control_center.models', fromlist=['CommandRequest']).CommandRequest(command_id=uuid4(), robot_id=target, operation="stop", parameters={"reason": "FOLLOW_REJECTED"}))
                        except Exception: pass
                    mission["state"]="PAUSED"; mission["failure_code"]="FOLLOW_REJECTED"; self._set_formation(FormationMode.PAUSED, "FOLLOW_REJECTED"); self.storage.update_mission(mission_id, mission); return False, {"reason_code":"FOLLOW_REJECTED"}
            mission["state"]="RUNNING"; self._set_formation(FormationMode.FOLLOWING); self.active_id=mission_id
            await self._navigate(mission, mission_id)
            if mission["state"] == "FAILED": self.storage.update_mission(mission_id, mission); return False, {"reason_code": "NAVIGATION_REJECTED"}
        elif action in {"pause", "cancel"}:
            if action == "cancel" and mission["state"] in {"DRAFT", "READY"}:
                mission["state"] = "CANCELED"
                self.storage.update_mission(mission_id, mission)
                return True, {"mission_id": mission_id, "mission_state": mission["state"]}
            mission["state"] = "PAUSING" if action == "pause" else "CANCELING"
            unconfirmed = []
            for robot_id, op in ((mission["master_id"], "cancel_navigation"), (mission["master_id"], "stop"), (mission["slave_id"], "stop")):
                try:
                    accepted = await self.adapter.execute(__import__('pinky_control_center.models', fromlist=['CommandRequest']).CommandRequest(command_id=uuid4(), robot_id=robot_id, operation=op, parameters={"reason": action.upper()}))
                    if not accepted.accepted: unconfirmed.append(robot_id)
                except Exception: unconfirmed.append(robot_id)
            if unconfirmed:
                mission["failure_code"] = "STOP_UNCONFIRMED"
                self.storage.update_mission(mission_id, mission)
                return False, {"mission_id": mission_id, "mission_state": mission["state"], "targets": [{"robot_id": robot_id, "state": "UNCONFIRMED" if robot_id in unconfirmed else "ACKNOWLEDGED"} for robot_id in (mission["master_id"], mission["slave_id"])]}
            self._set_formation(FormationMode.PAUSED)
        self.storage.update_mission(mission_id, mission); return True, {"mission_id": mission_id, "mission_state": mission["state"]}
