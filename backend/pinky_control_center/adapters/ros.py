"""Per-robot rosbridge adapter.

This module deliberately owns two independent websocket clients.  A ROS 2
domain is selected by the rosbridge process, never by a browser request or a
dashboard command.  The adapter therefore uses the fixed, validated mapping
in :class:`RosbridgeConfig` as its only routing authority.
"""
from __future__ import annotations

import asyncio
import base64
import inspect
import json
import math
import time
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from io import BytesIO
from typing import Any, Literal
from uuid import uuid4

import websockets
from PIL import Image

from pinky_control_center.config import RosbridgeConfig, RosbridgeRobotConfig
from pinky_control_center.models import (
    AdapterEvent, CameraFrame, CommandAcceptance, CommandRequest, Connection,
    FormationMode, FormationState, Freshness, Pose, RobotMode, RobotState,
    SensorState, SensorStatus, StateSnapshot,
)

RobotId = Literal["robot_1", "robot_2"]
_RECONNECT_DELAYS = (1, 2, 4, 8)


class RosbridgeAdapter:
    """Translate rosbridge JSON into the existing adapter contract.

    `connect_factory` is injectable so protocol tests do not need ROS or a
    network endpoint.  A transport failure only changes the matching robot's
    state; it cannot redirect a command to the other robot.
    """

    def __init__(
        self,
        config: RosbridgeConfig,
        *,
        connect_factory: Callable[..., Any] = websockets.connect,
        clock: Callable[[], datetime] | None = None,
        reconnect_delays: tuple[int, ...] = _RECONNECT_DELAYS,
    ) -> None:
        self.config = config
        self._by_id: dict[RobotId, RosbridgeRobotConfig] = {robot.robot_id: robot for robot in config.robots}
        self._connect_factory = connect_factory
        self._clock = clock or (lambda: datetime.now(UTC))
        self._reconnect_delays = reconnect_delays
        self._sockets: dict[RobotId, Any] = {}
        self._tasks: dict[RobotId, asyncio.Task[None]] = {}
        self._connected = False
        self._event_queue: asyncio.Queue[AdapterEvent] = asyncio.Queue(maxsize=200)
        self._drained_events: list[AdapterEvent] = []
        self._frames: dict[RobotId, CameraFrame] = {}
        self._service_calls: dict[str, asyncio.Future[CommandAcceptance]] = {}
        self._states: dict[RobotId, RobotState] = {
            robot_id: self._blank_state(robot) for robot_id, robot in self._by_id.items()
        }

    def _blank_state(self, robot: RosbridgeRobotConfig) -> RobotState:
        return RobotState(
            robot_id=robot.robot_id, name=robot.name, role=robot.role,
            connection=Connection.OFFLINE, received_at=None, pose=None,
            pose_freshness=Freshness.UNKNOWN, battery_freshness=Freshness.UNKNOWN,
            mode=RobotMode.UNKNOWN, tf_valid=False, tf_reason_code="ROSBRIDGE_OFFLINE",
            sensors=[SensorStatus(name="camera", state=SensorState.STALE)],
        )

    async def connect(self) -> None:
        if self._connected:
            return
        self._connected = True
        for robot_id in ("robot_1", "robot_2"):
            self._tasks[robot_id] = asyncio.create_task(self._run(robot_id))
        # Let immediately available test/live transports subscribe before a
        # caller inspects the snapshot, without waiting for unavailable robots.
        await asyncio.sleep(0)

    async def close(self) -> None:
        self._connected = False
        tasks = list(self._tasks.values())
        self._tasks.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for socket in list(self._sockets.values()):
            closer = getattr(socket, "close", None)
            if closer:
                result = closer()
                if inspect.isawaitable(result):
                    await result
        self._sockets.clear()
        for future in self._service_calls.values():
            if not future.done():
                future.set_result(CommandAcceptance(accepted=False, reason_code="ROSBRIDGE_CLOSED"))
        self._service_calls.clear()
        for robot_id in self._states:
            self._mark_disconnected(robot_id)

    async def _open(self, url: str) -> Any:
        candidate = self._connect_factory(url, open_timeout=5)
        if inspect.isawaitable(candidate):
            return await candidate
        return candidate

    async def _run(self, robot_id: RobotId) -> None:
        retry = 0
        while self._connected:
            socket: Any | None = None
            try:
                socket = await self._open(self._by_id[robot_id].bridge_url)
                self._sockets[robot_id] = socket
                self._mark_connected(robot_id)
                await self._subscribe(robot_id, socket)
                retry = 0
                while self._connected:
                    raw = await socket.recv()
                    if raw is None:
                        raise ConnectionError("rosbridge closed")
                    await self._handle_raw(robot_id, raw)
            except asyncio.CancelledError:
                raise
            except Exception:
                self._mark_disconnected(robot_id)
                delay = self._reconnect_delays[min(retry, len(self._reconnect_delays) - 1)]
                retry += 1
                if self._connected:
                    await asyncio.sleep(delay)
            finally:
                if self._sockets.get(robot_id) is socket:
                    self._sockets.pop(robot_id, None)
                if socket is not None:
                    closer = getattr(socket, "close", None)
                    if closer:
                        try:
                            result = closer()
                            if inspect.isawaitable(result):
                                await result
                        except Exception:
                            pass

    async def _subscribe(self, robot_id: RobotId, socket: Any) -> None:
        robot = self._by_id[robot_id]
        topics = robot.topics
        subscriptions = (
            (topics.odom, "nav_msgs/msg/Odometry", 0),
            (topics.battery_percent, "std_msgs/msg/Float32", 0),
            (topics.battery_voltage, "std_msgs/msg/Float32", 0),
            (topics.control_status, None, 0),
            (topics.camera_compressed, "sensor_msgs/msg/CompressedImage", robot.camera.throttle_rate_ms),
        )
        for topic, message_type, throttle_rate in subscriptions:
            payload: dict[str, object] = {"op": "subscribe", "topic": topic, "queue_length": 1}
            if message_type:
                payload["type"] = message_type
            if throttle_rate:
                payload.update({"throttle_rate": throttle_rate, "fragment_size": robot.camera.fragment_size})
            await socket.send(json.dumps(payload, separators=(",", ":")))
        if topics.path:
            await socket.send(json.dumps({"op": "subscribe", "topic": topics.path, "type": "nav_msgs/msg/Path", "queue_length": 1}, separators=(",", ":")))

    def _mark_connected(self, robot_id: RobotId) -> None:
        now = self._clock()
        current = self._states[robot_id]
        self._states[robot_id] = current.model_copy(update={
            "connection": Connection.ONLINE, "received_at": now,
            "tf_reason_code": "TF_UNAVAILABLE" if current.pose is None else current.tf_reason_code,
        })

    def _mark_disconnected(self, robot_id: RobotId) -> None:
        current = self._states[robot_id]
        self._states[robot_id] = current.model_copy(update={
            "connection": Connection.OFFLINE, "received_at": None,
            "pose_freshness": Freshness.UNKNOWN, "battery_freshness": Freshness.UNKNOWN,
            "tf_valid": False, "tf_reason_code": "ROSBRIDGE_OFFLINE",
            "sensors": [SensorStatus(name="camera", state=SensorState.STALE)],
        })

    async def _handle_raw(self, robot_id: RobotId, raw: str | bytes) -> None:
        try:
            payload = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict):
            return
        if payload.get("op") == "service_response":
            self._complete_service_call(payload)
            return
        if payload.get("op") != "publish" or not isinstance(payload.get("topic"), str) or not isinstance(payload.get("msg"), dict):
            return
        await self.handle_publish(robot_id, payload["topic"], payload["msg"])

    def _complete_service_call(self, payload: dict[str, object]) -> None:
        call_id = payload.get("id")
        if not isinstance(call_id, str):
            return
        future = self._service_calls.pop(call_id, None)
        if future is None or future.done():
            return
        values = payload.get("values")
        accepted = bool(payload.get("result", False))
        reason: str | None = None
        if isinstance(values, dict):
            accepted = bool(values.get("accepted", accepted))
            value_reason = values.get("reason_code")
            reason = value_reason if isinstance(value_reason, str) else None
        future.set_result(CommandAcceptance(accepted=accepted, reason_code=reason if not accepted else None))

    async def handle_publish(self, robot_id: RobotId, topic: str, message: dict[str, object]) -> None:
        """Public protocol seam used by contract tests and rosbridge readers."""
        robot = self._by_id[robot_id]
        now = self._clock()
        if topic == robot.topics.odom:
            self._update_odom(robot_id, message, now)
            await self._emit("robot_state", robot_id, self._states[robot_id].model_dump(mode="json"), now)
        elif topic in {robot.topics.battery_percent, robot.topics.battery_voltage}:
            self._update_battery(robot_id, topic, message, now)
            await self._emit("robot_state", robot_id, self._states[robot_id].model_dump(mode="json"), now)
        elif topic == robot.topics.control_status:
            self._update_control_status(robot_id, message, now)
            await self._emit("robot_state", robot_id, self._states[robot_id].model_dump(mode="json"), now)
        elif topic == robot.topics.camera_compressed:
            frame = self._decode_camera(robot_id, message, now)
            if frame:
                self._frames[robot_id] = frame
        elif robot.topics.path and topic == robot.topics.path:
            await self._emit("path", robot_id, self._path_payload(robot_id, message), now)

    def _update_odom(self, robot_id: RobotId, message: dict[str, object], now: datetime) -> None:
        pose_part = _nested_dict(message, "pose", "pose")
        position = _nested_dict(pose_part, "position")
        orientation = _nested_dict(pose_part, "orientation")
        twist = _nested_dict(message, "twist", "twist")
        linear = _nested_dict(twist, "linear")
        angular = _nested_dict(twist, "angular")
        try:
            pose = Pose(x=float(position["x"]), y=float(position["y"]), yaw=_yaw(orientation), frame_id=_frame_id(message, "odom"))
        except (KeyError, TypeError, ValueError):
            return
        # Odom is deliberately not presented as a common-map pose.  A verified
        # map->odom TF subscription is required before tf_valid can become true.
        self._states[robot_id] = self._states[robot_id].model_copy(update={
            "connection": Connection.ONLINE, "received_at": now, "pose": pose,
            "pose_freshness": Freshness.FRESH, "linear_mps": _number(linear.get("x")),
            "angular_rps": _number(angular.get("z")), "tf_valid": False,
            "tf_reason_code": "MAP_TF_UNVERIFIED",
        })

    def _update_battery(self, robot_id: RobotId, topic: str, message: dict[str, object], now: datetime) -> None:
        value = _number(message.get("data"))
        if value is None:
            return
        updates: dict[str, object] = {"connection": Connection.ONLINE, "received_at": now, "battery_freshness": Freshness.FRESH}
        if topic == self._by_id[robot_id].topics.battery_percent:
            updates["battery_percent"] = max(0.0, min(100.0, value * 100 if value <= 1 else value))
        else:
            updates["voltage_v"] = max(0.0, value)
        self._states[robot_id] = self._states[robot_id].model_copy(update=updates)

    def _update_control_status(self, robot_id: RobotId, message: dict[str, object], now: datetime) -> None:
        current = self._states[robot_id]
        mode_raw = message.get("mode")
        try:
            mode = RobotMode(str(mode_raw)) if mode_raw is not None else current.mode
        except ValueError:
            mode = RobotMode.UNKNOWN
        capabilities = message.get("capabilities")
        self._states[robot_id] = current.model_copy(update={
            "connection": Connection.ONLINE, "received_at": now, "mode": mode,
            "stop_latched": message.get("stop_latched") if isinstance(message.get("stop_latched"), bool) else current.stop_latched,
            "linear_mps": _number(message.get("linear_mps")) if _number(message.get("linear_mps")) is not None else current.linear_mps,
            "angular_rps": _number(message.get("angular_rps")) if _number(message.get("angular_rps")) is not None else current.angular_rps,
            "capabilities": [value for value in capabilities if isinstance(value, str)] if isinstance(capabilities, list) else current.capabilities,
        })

    def _decode_camera(self, robot_id: RobotId, message: dict[str, object], now: datetime) -> CameraFrame | None:
        encoded = message.get("data")
        if not isinstance(encoded, str):
            return None
        try:
            jpeg = base64.b64decode(encoded, validate=True)
            if not jpeg.startswith(b"\xff\xd8"):
                return None
            with Image.open(BytesIO(jpeg)) as image:
                width, height = image.size
        except (ValueError, OSError):
            return None
        header = _nested_dict(message, "header")
        stamp = _nested_dict(header, "stamp")
        captured_at = _ros_stamp(stamp)
        frame = CameraFrame(robot_id=robot_id, frame_id=str(_nested_dict(header).get("seq", uuid4())), captured_at=captured_at, received_at=now, width=width, height=height, jpeg=jpeg)
        self._states[robot_id] = self._states[robot_id].model_copy(update={
            "sensors": [SensorStatus(name="camera", state=SensorState.OK, received_at=now)]
        })
        return frame

    def _path_payload(self, robot_id: RobotId, message: dict[str, object]) -> dict[str, object]:
        points: list[dict[str, float]] = []
        poses = message.get("poses")
        if isinstance(poses, list):
            for item in poses[:200]:
                if not isinstance(item, dict):
                    continue
                position = _nested_dict(item, "pose", "position")
                x, y = _number(position.get("x")), _number(position.get("y"))
                if x is not None and y is not None:
                    points.append({"x": x, "y": y})
        return {"robot_id": robot_id, "frame_id": _frame_id(message, ""), "points": points}

    async def _emit(self, kind: Literal["robot_state", "formation", "command", "map", "path", "scan", "costmap"], robot_id: RobotId | None, payload: dict[str, object], now: datetime) -> None:
        event = AdapterEvent(kind=kind, robot_id=robot_id, payload=payload, received_at=now)
        self._drained_events.append(event)
        if self._event_queue.full():
            self._event_queue.get_nowait()
        self._event_queue.put_nowait(event)

    def snapshot(self) -> StateSnapshot:
        now = self._clock()
        return StateSnapshot(
            robots=[self._states["robot_1"], self._states["robot_2"]],
            formation=FormationState(state=FormationMode.UNPAIRED, master_id="robot_1", slave_id="robot_2", target_distance_m=0.8),
            mode="ros", seq=0, server_time=now, map_id="unknown",
        )

    def frame(self, robot_id: str) -> CameraFrame | None:
        return self._frames.get(robot_id) if robot_id in self._by_id else None

    def drain_events(self) -> list[AdapterEvent]:
        events, self._drained_events = self._drained_events, []
        return events

    async def events(self) -> AsyncIterator[AdapterEvent]:
        while self._connected:
            yield await self._event_queue.get()

    async def frames(self, robot_id: str) -> AsyncIterator[CameraFrame]:
        last_id: str | None = None
        while self._connected and robot_id in self._by_id:
            frame = self.frame(robot_id)
            if frame and frame.frame_id != last_id:
                last_id = frame.frame_id
                yield frame
            await asyncio.sleep(0.05)

    async def execute(self, command: CommandRequest) -> CommandAcceptance:
        robot_id = command.robot_id
        robot = self._by_id[robot_id]
        socket = self._sockets.get(robot_id)
        if socket is None:
            return CommandAcceptance(accepted=False, reason_code="ROSBRIDGE_OFFLINE")
        service = robot.services
        if command.operation.startswith("follow_"):
            if not service.follow_available or not service.follow_command or not service.follow_command_type:
                return CommandAcceptance(accepted=False, reason_code="UNSUPPORTED")
            endpoint, service_type = service.follow_command, service.follow_command_type
        else:
            # The robot-side control mediator is mandatory: this adapter never
            # writes /cmd_vel directly.  Unconfirmed service contracts stay
            # explicitly unsupported even if a placeholder name is configured.
            if not service.control_available:
                return CommandAcceptance(accepted=False, reason_code="UNSUPPORTED")
            endpoint, service_type = service.control_command, service.control_command_type
        call_id = f"cc:{command.command_id}:{robot_id}"
        future: asyncio.Future[CommandAcceptance] = asyncio.get_running_loop().create_future()
        self._service_calls[call_id] = future
        request = {
            "op": "call_service", "id": call_id, "service": endpoint,
            "type": service_type,
            "args": {"command_id": str(command.command_id), "operation": command.operation, "parameters": command.parameters},
        }
        try:
            await socket.send(json.dumps(request, separators=(",", ":")))
            return await asyncio.wait_for(future, timeout=2.0)
        except asyncio.TimeoutError:
            return CommandAcceptance(accepted=False, reason_code="ROSBRIDGE_TIMEOUT")
        except Exception:
            return CommandAcceptance(accepted=False, reason_code="ROSBRIDGE_WRITE_FAILED")
        finally:
            self._service_calls.pop(call_id, None)

    async def apply_settings(self, values: dict[str, object]) -> bool:
        """ROS parameter/settings application has no confirmed T12 contract yet."""
        return False


def _nested_dict(value: object, *keys: str) -> dict[str, object]:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return {}
        current = current.get(key)
    return current if isinstance(current, dict) else {}


def _number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _yaw(orientation: dict[str, object]) -> float:
    x, y, z, w = (_number(orientation.get(axis)) for axis in ("x", "y", "z", "w"))
    if None in {x, y, z, w}:
        raise ValueError("invalid quaternion")
    return math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))  # type: ignore[operator]


def _frame_id(message: dict[str, object], fallback: str) -> str:
    value = _nested_dict(message, "header").get("frame_id")
    return value if isinstance(value, str) and value else fallback


def _ros_stamp(stamp: dict[str, object]) -> datetime | None:
    seconds, nanoseconds = _number(stamp.get("sec")), _number(stamp.get("nanosec"))
    if seconds is None or nanoseconds is None:
        return None
    try:
        return datetime.fromtimestamp(seconds + nanoseconds / 1_000_000_000, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None
