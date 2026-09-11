from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import HTTPException

from pinky_control_center.models import Connection, FormationMode, FormationState, Freshness, MissionState, Pose, UserInfo


class MissionService:
    """T06 orchestration. Adapter calls are deliberately ordered here, before ROS actions exist."""
    def __init__(self, storage, adapter, state_store, clock) -> None:
        self.storage, self.adapter, self.state_store, self.clock = storage, adapter, state_store, clock
        self.active_id: str | None = None
        self.slave_wait_deadline: float | None = None
        self.formation_pause_pending: tuple[str, str] | None = None
        # Recovery never resumes motion. Persisted in-flight missions need operator action.
        import json
        for row in self.storage.connection.execute("SELECT id,payload_json FROM missions WHERE state IN ('STARTING','RUNNING','PAUSING','CANCELING')"):
            payload = json.loads(row["payload_json"])
            payload["state"] = "PAUSED"; payload["failure_code"] = "SERVER_RESTART"
            self.storage.update_mission(row["id"], payload)

    def master_navigation_succeeded(self, mission_id: str) -> None:
        """Adapter result hook: master success is not mission success until the slave is settled."""
        if mission_id == self.active_id:
            self.slave_wait_deadline = self.clock() + 10.0

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
        """Complete transitional states only from fresh stop observations."""
        if self.formation_pause_pending:
            master, slave = self.formation_pause_pending
            robots = {robot.robot_id: robot for robot in self.state_store.snapshot().robots}
            if all(robots[robot_id].stop_latched and robots[robot_id].pose_freshness == Freshness.FRESH and abs(robots[robot_id].linear_mps or 0) < .01 and abs(robots[robot_id].angular_rps or 0) < .02 for robot_id in (master, slave)):
                self._set_formation(FormationMode.PAUSED)
                self.formation_pause_pending = None
        if not self.active_id:
            return
        row = self.storage.connection.execute("SELECT payload_json FROM missions WHERE id=?", (self.active_id,)).fetchone()
        if not row:
            return
        import json
        mission = json.loads(row["payload_json"])
        if self.slave_wait_deadline is not None and self.clock() >= self.slave_wait_deadline and mission["state"] == "RUNNING":
            mission["state"] = "PAUSED"; mission["failure_code"] = "SLAVE_SETTLE_TIMEOUT"
            self._set_formation(FormationMode.PAUSED, "SLAVE_SETTLE_TIMEOUT")
            self.slave_wait_deadline = None
            self.storage.update_mission(self.active_id, mission)
            return
        source = self.state_store.snapshot_source()
        source_formation = source.formation
        if source_formation.state == FormationMode.LOST and mission["state"] in {"RUNNING", "STARTING"}:
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
            self.state_store.formation_override = FormationState(state=FormationMode.READY, master_id=master, slave_id=slave, target_distance_m=.8)
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
        if not isinstance(waypoints, list) or len(waypoints) != 1:
            raise HTTPException(422, detail="INVALID_VALUE")
        try: Pose.model_validate(waypoints[0])
        except Exception as error: raise HTTPException(422, detail="INVALID_VALUE") from error
        data = {"name": payload.get("name"), "state": MissionState.DRAFT.value, "master_id": self.formation().master_id, "slave_id": self.formation().slave_id, "map_id": payload.get("map_id"), "waypoints": waypoints, "repeat_count": payload.get("repeat_count", 1), "waypoint_index": 0, "lap_index": 0, "progress_distance_m": None, "failure_code": None}
        if not isinstance(data["name"], str) or not isinstance(data["map_id"], str) or data["map_id"] != "mock_lab" or not isinstance(data["repeat_count"], int) or not 1 <= data["repeat_count"] <= 100: raise HTTPException(422, detail="INVALID_VALUE")
        return self.storage.create_mission_idempotent(user, UUID(str(payload["request_id"])), data)

    def action(self, user: UserInfo, mission_id: str, request_id: UUID, action: str, dispatcher):
        mission = self.storage.mission(mission_id, user)
        if mission is None: raise HTTPException(404, detail="MISSION_NOT_FOUND")
        state = mission["state"]
        valid = {"validate": {"DRAFT"}, "start": {"READY", "PAUSED"}, "pause": {"RUNNING"}, "resume": {"PAUSED"}, "cancel": {"DRAFT", "READY", "RUNNING", "PAUSED"}}
        if action not in valid or state not in valid[action]: raise HTTPException(409, detail="INVALID_STATE")
        if action in {"start", "resume"} and self.formation().state not in {FormationMode.READY, FormationMode.PAUSED}: raise HTTPException(409, detail="INVALID_STATE")
        return dispatcher.submit(user, request_id, mission_id, "mission_" + action, parameters={"mission_id": mission_id})

    async def execute_mission(self, operation: str, parameters: dict[str, object], user: UserInfo | None = None) -> tuple[bool, dict[str, object]]:
        mission_id = str(parameters["mission_id"])
        row = self.storage.connection.execute("SELECT payload_json FROM missions WHERE id=?", (mission_id,)).fetchone()
        if not row: return False, {"reason_code": "MISSION_NOT_FOUND"}
        import json
        mission = json.loads(row["payload_json"]); action = operation.removeprefix("mission_")
        if action == "validate": mission["state"] = "READY"
        elif action in {"start", "resume"}:
            mission["state"] = "STARTING"; slave, master = mission["slave_id"], mission["master_id"]
            calls = [(slave, "follow_ready", {}), (slave, "follow_start", {}), (master, "navigate", {"goal": mission["waypoints"][mission["waypoint_index"]], "mission_id": mission_id})]
            for robot_id, op, params in calls:
                accepted = await self.adapter.execute(__import__('pinky_control_center.models', fromlist=['CommandRequest']).CommandRequest(command_id=uuid4(), robot_id=robot_id, operation=op, parameters=params))
                if not accepted.accepted:
                    for target in ("robot_1", "robot_2"):
                        try: await self.adapter.execute(__import__('pinky_control_center.models', fromlist=['CommandRequest']).CommandRequest(command_id=uuid4(), robot_id=target, operation="stop", parameters={"reason": "FOLLOW_REJECTED"}))
                        except Exception: pass
                    mission["state"]="PAUSED"; mission["failure_code"]="FOLLOW_REJECTED"; self._set_formation(FormationMode.PAUSED, "FOLLOW_REJECTED"); self.storage.update_mission(mission_id, mission); return False, {"reason_code":"FOLLOW_REJECTED"}
            mission["state"]="RUNNING"; self._set_formation(FormationMode.FOLLOWING); self.active_id=mission_id
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
