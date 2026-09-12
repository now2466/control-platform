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
from geometry_msgs.msg import Twist, TwistStamped
from pinky_control_interfaces.msg import ControlStatus
from pinky_control_interfaces.srv import ControlCommand
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
            f"limits={self.max_linear:.2f}m/s/{self.max_angular:.2f}rad/s"
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
            self.stop_latched = True
            self.mode = "STOPPED"
            self.reason_code = "OPERATOR_STOP"
        elif operation == "reset_stop":
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
            self.mode = str(mode)
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
        if time.monotonic() - self._nav.received_at <= self.nav_timeout:
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
