#!/usr/bin/env python3
"""Arbitrate Pinky velocity commands with a wall-clock deadman watchdog.

The hardware bringup owns the final ``/cmd_vel`` subscriber.  This node is
the only publisher in front of it: manual commands arrive as TwistStamped on
``/control/manual_velocity`` and navigation commands may arrive as Twist on
``/control/nav_velocity``.  A stale input always becomes zero.
"""

from __future__ import annotations

import json
import math
import time
from collections import deque
from dataclasses import dataclass

import rclpy
from action_msgs.msg import GoalStatus
from geometry_msgs.msg import Twist, TwistStamped
from nav2_msgs.action import NavigateToPose
from pinky_control_interfaces.msg import ControlStatus
from pinky_control_interfaces.srv import ControlCommand
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.qos import QoSProfile, QoSReliabilityPolicy
from std_msgs.msg import UInt64


@dataclass
class _Velocity:
    linear: float = 0.0
    angular: float = 0.0
    received_at: float = 0.0


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


class ManualVelocityWatchdog(Node):
    """Safety gate with stop-latch, mode gate, limits, and deadman timeout."""

    def __init__(self) -> None:
        super().__init__("pinky_control_watchdog")
        self.declare_parameter("robot_id", "robot_2")
        self.declare_parameter("manual_topic", "/control/manual_velocity")
        self.declare_parameter("nav_topic", "/control/nav_velocity")
        self.declare_parameter("navigate_action_name", "/navigate_to_pose")
        self.declare_parameter("cmd_vel_topic", "/cmd_vel")
        self.declare_parameter("status_topic", "/control/status")
        self.declare_parameter("heartbeat_topic", "/control/heartbeat")
        self.declare_parameter("manual_timeout_sec", 0.35)
        self.declare_parameter("nav_timeout_sec", 0.50)
        self.declare_parameter("max_linear_mps", 0.15)
        self.declare_parameter("max_angular_rps", 0.50)
        self.declare_parameter("publish_rate_hz", 20.0)
        self.declare_parameter("status_rate_hz", 10.0)

        self.robot_id = str(self.get_parameter("robot_id").value)
        self.manual_timeout = float(self.get_parameter("manual_timeout_sec").value)
        self.nav_timeout = float(self.get_parameter("nav_timeout_sec").value)
        self.max_linear = float(self.get_parameter("max_linear_mps").value)
        self.max_angular = float(self.get_parameter("max_angular_rps").value)
        self.mode = "STOPPED"
        self.stop_latched = True
        self.reason_code = "STARTUP_STOP_LATCH"
        self._active_command_id = ""
        self._command_state = "IDLE"
        self._manual = _Velocity()
        self._nav = _Velocity()
        self._last_output = _Velocity()
        self._heartbeat = 0
        self._recent_command_ids: deque[str] = deque(maxlen=128)
        self._nav_client = ActionClient(
            self,
            NavigateToPose,
            str(self.get_parameter("navigate_action_name").value),
        )
        self._nav_goal_handle = None
        self._nav_command_id = ""
        self._canceled_navigation_ids: set[str] = set()
        self._navigation_terminal_at = 0.0

        reliable = QoSProfile(depth=10, reliability=QoSReliabilityPolicy.RELIABLE)
        self._cmd_pub = self.create_publisher(
            Twist, str(self.get_parameter("cmd_vel_topic").value), reliable
        )
        self._status_pub = self.create_publisher(
            ControlStatus, str(self.get_parameter("status_topic").value), reliable
        )
        self._heartbeat_pub = self.create_publisher(
            UInt64, str(self.get_parameter("heartbeat_topic").value), reliable
        )
        self.create_subscription(
            TwistStamped,
            str(self.get_parameter("manual_topic").value),
            self._manual_callback,
            reliable,
        )
        self.create_subscription(
            Twist,
            str(self.get_parameter("nav_topic").value),
            self._nav_callback,
            reliable,
        )
        self.create_service(
            ControlCommand,
            "/control/command",
            self._command_callback,
        )
        self.create_timer(1.0 / max(float(self.get_parameter("publish_rate_hz").value), 1.0), self._publish_output)
        self.create_timer(1.0 / max(float(self.get_parameter("status_rate_hz").value), 1.0), self._publish_status)
        self.get_logger().info(
            f"Pinky control watchdog ready: robot_id={self.robot_id}, "
            f"manual_timeout={self.manual_timeout:.2f}s, "
            f"limits={self.max_linear:.2f}m/s/{self.max_angular:.2f}rad/s, "
            f"navigate_action={self.get_parameter('navigate_action_name').value}"
        )

    def _manual_callback(self, message: TwistStamped) -> None:
        linear = float(message.twist.linear.x)
        angular = float(message.twist.angular.z)
        if not _finite(linear) or not _finite(angular):
            self.reason_code = "INVALID_MANUAL_VELOCITY"
            return
        self._manual = _Velocity(
            linear=max(-self.max_linear, min(self.max_linear, linear)),
            angular=max(-self.max_angular, min(self.max_angular, angular)),
            received_at=time.monotonic(),
        )

    def _nav_callback(self, message: Twist) -> None:
        linear = float(message.linear.x)
        angular = float(message.angular.z)
        if not _finite(linear) or not _finite(angular):
            self.reason_code = "INVALID_NAV_VELOCITY"
            return
        self._nav = _Velocity(
            linear=max(-self.max_linear, min(self.max_linear, linear)),
            angular=max(-self.max_angular, min(self.max_angular, angular)),
            received_at=time.monotonic(),
        )

    def _command_callback(self, request: ControlCommand.Request, response: ControlCommand.Response):
        command_id = str(request.command_id)
        if command_id and command_id in self._recent_command_ids:
            response.accepted = True
            response.reason_code = "DUPLICATE_IGNORED"
            return response
        if command_id:
            self._recent_command_ids.append(command_id)
        operation = str(request.operation)
        self._active_command_id = command_id
        self._command_state = "RUNNING"
        self.reason_code = ""
        try:
            parameters = json.loads(request.parameters_json or "{}")
        except json.JSONDecodeError:
            return self._reject(response, "INVALID_PARAMETERS")
        if not isinstance(parameters, dict):
            return self._reject(response, "INVALID_PARAMETERS")

        if operation == "stop":
            self._cancel_navigation()
            self.stop_latched = True
            self.mode = "STOPPED"
            self.reason_code = "OPERATOR_STOP"
        elif operation == "reset_stop":
            # Releasing the latch must never resume a goal that was accepted
            # before the stop.  A new map request must send a new goal.
            self._cancel_navigation()
            self.stop_latched = False
            self.mode = "IDLE"
            self.reason_code = "STOP_RESET_NO_AUTO_RESUME"
        elif operation == "set_mode":
            mode = parameters.get("mode")
            if mode not in {"IDLE", "AUTO", "FOLLOW", "MANUAL", "STOPPED"}:
                return self._reject(response, "INVALID_MODE")
            if mode == "STOPPED":
                self.stop_latched = True
            elif self.stop_latched:
                return self._reject(response, "STOP_LATCHED")
            if mode != "AUTO":
                self._cancel_navigation()
            self.mode = str(mode)
        elif operation == "navigate":
            return self._start_navigation(parameters, command_id, response)
        elif operation == "cancel_navigation":
            self._cancel_navigation()
            if not self.stop_latched:
                self.mode = "IDLE"
            self.reason_code = "NAVIGATION_CANCELED"
        elif operation == "apply_settings":
            values = parameters.get("values", parameters)
            if not isinstance(values, dict):
                return self._reject(response, "INVALID_PARAMETERS")
            if "max_linear_mps" in values:
                if not _finite(values["max_linear_mps"]) or float(values["max_linear_mps"]) <= 0:
                    return self._reject(response, "INVALID_SPEED_LIMIT")
                self.max_linear = float(values["max_linear_mps"])
            if "max_angular_rps" in values:
                if not _finite(values["max_angular_rps"]) or float(values["max_angular_rps"]) <= 0:
                    return self._reject(response, "INVALID_SPEED_LIMIT")
                self.max_angular = float(values["max_angular_rps"])
        else:
            return self._reject(response, "UNSUPPORTED_OPERATION")

        self._command_state = "SUCCEEDED"
        self._active_command_id = ""
        response.accepted = True
        response.reason_code = ""
        return response

    def _reject(self, response: ControlCommand.Response, reason: str):
        self._command_state = "REJECTED"
        self.reason_code = reason
        self._active_command_id = ""
        response.accepted = False
        response.reason_code = reason
        return response

    def _start_navigation(self, parameters: dict[str, object], command_id: str, response: ControlCommand.Response):
        if self.stop_latched:
            return self._reject(response, "STOP_LATCHED")
        if self._nav_command_id or self._nav_goal_handle is not None:
            return self._reject(response, "NAVIGATION_BUSY")
        if not self._nav_client.wait_for_server(timeout_sec=0.25):
            return self._reject(response, "NAVIGATION_UNAVAILABLE")
        goal = parameters.get("goal")
        if not isinstance(goal, dict):
            return self._reject(response, "INVALID_GOAL")
        frame_id = goal.get("frame_id", "map")
        values = (goal.get("x"), goal.get("y"), goal.get("yaw"))
        if not isinstance(frame_id, str) or not frame_id or not all(_finite(value) for value in values):
            return self._reject(response, "INVALID_GOAL")

        goal_message = NavigateToPose.Goal()
        goal_message.pose.header.frame_id = frame_id
        goal_message.pose.header.stamp = self.get_clock().now().to_msg()
        goal_message.pose.pose.position.x = float(goal["x"])
        goal_message.pose.pose.position.y = float(goal["y"])
        goal_message.pose.pose.position.z = 0.0
        goal_message.pose.pose.orientation.z = math.sin(float(goal["yaw"]) / 2.0)
        goal_message.pose.pose.orientation.w = math.cos(float(goal["yaw"]) / 2.0)

        self._nav_command_id = command_id
        self._active_command_id = command_id
        self._command_state = "RUNNING"
        self.reason_code = "NAVIGATION_REQUESTED"
        self._navigation_terminal_at = 0.0
        try:
            future = self._nav_client.send_goal_async(goal_message)
            future.add_done_callback(lambda result: self._goal_response_callback(command_id, result))
        except Exception:
            self._nav_command_id = ""
            return self._reject(response, "NAVIGATION_SEND_FAILED")
        response.accepted = True
        response.reason_code = ""
        return response

    def _goal_response_callback(self, command_id: str, future) -> None:
        try:
            goal_handle = future.result()
        except Exception:
            if command_id not in self._canceled_navigation_ids:
                self._finish_navigation(command_id, "FAILED", "NAVIGATION_SEND_FAILED")
            else:
                self._canceled_navigation_ids.discard(command_id)
            return
        if command_id in self._canceled_navigation_ids:
            self._canceled_navigation_ids.discard(command_id)
            if goal_handle.accepted:
                goal_handle.cancel_goal_async()
            return
        if command_id != self._nav_command_id:
            if goal_handle.accepted:
                goal_handle.cancel_goal_async()
            return
        if not goal_handle.accepted:
            self._finish_navigation(command_id, "REJECTED", "NAVIGATION_GOAL_REJECTED")
            return
        self._nav_goal_handle = goal_handle
        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(lambda result: self._goal_result_callback(command_id, result))

    def _goal_result_callback(self, command_id: str, future) -> None:
        if command_id != self._nav_command_id:
            return
        try:
            status = int(future.result().status)
        except Exception:
            self._finish_navigation(command_id, "FAILED", "NAVIGATION_RESULT_UNAVAILABLE")
            return
        if status == GoalStatus.STATUS_SUCCEEDED:
            self._finish_navigation(command_id, "SUCCEEDED", "NAVIGATION_SUCCEEDED")
        elif status == GoalStatus.STATUS_CANCELED:
            self._finish_navigation(command_id, "CANCELED", "NAVIGATION_CANCELED")
        else:
            self._finish_navigation(command_id, "FAILED", "NAVIGATION_FAILED")

    def _finish_navigation(self, command_id: str, state: str, reason: str) -> None:
        if command_id != self._nav_command_id:
            return
        self._nav_goal_handle = None
        self._nav_command_id = ""
        self._active_command_id = ""
        self._command_state = state
        self.reason_code = reason
        self.mode = "IDLE"
        self._navigation_terminal_at = time.monotonic()

    def _cancel_navigation(self) -> None:
        command_id = self._nav_command_id
        goal_handle = self._nav_goal_handle
        if command_id:
            self._canceled_navigation_ids.add(command_id)
        self._nav_command_id = ""
        self._nav_goal_handle = None
        self._active_command_id = ""
        if goal_handle is not None:
            try:
                goal_handle.cancel_goal_async()
            except Exception:
                pass

    def _publish_output(self) -> None:
        now = time.monotonic()
        output = _Velocity()
        if not self.stop_latched:
            if self.mode == "MANUAL" and now - self._manual.received_at <= self.manual_timeout:
                output = self._manual
            elif self.mode in {"AUTO", "FOLLOW"} and now - self._nav.received_at <= self.nav_timeout:
                output = self._nav
            elif self.mode in {"MANUAL", "AUTO", "FOLLOW"}:
                self.reason_code = "VELOCITY_WATCHDOG_TIMEOUT"
        output = _Velocity(
            linear=max(-self.max_linear, min(self.max_linear, output.linear)),
            angular=max(-self.max_angular, min(self.max_angular, output.angular)),
            received_at=now,
        )
        message = Twist()
        message.linear.x = output.linear
        message.angular.z = output.angular
        self._cmd_pub.publish(message)
        self._last_output = output

    def _publish_status(self) -> None:
        if self._navigation_terminal_at and time.monotonic() - self._navigation_terminal_at > 1.0:
            self._navigation_terminal_at = 0.0
            self._command_state = "IDLE"
            self.reason_code = ""
        self._heartbeat += 1
        status = ControlStatus()
        status.stamp = self.get_clock().now().to_msg()
        status.robot_id = self.robot_id
        status.mode = self.mode
        status.stop_latched = self.stop_latched
        status.active_command_id = self._active_command_id
        status.command_state = self._command_state
        status.reason_code = self.reason_code
        status.capabilities = ["manual"]
        if self._nav_client.server_is_ready():
            status.capabilities.append("navigate")
        status.linear_mps = self._last_output.linear
        status.angular_rps = self._last_output.angular
        self._status_pub.publish(status)
        heartbeat = UInt64()
        heartbeat.data = self._heartbeat
        self._heartbeat_pub.publish(heartbeat)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = ManualVelocityWatchdog()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
