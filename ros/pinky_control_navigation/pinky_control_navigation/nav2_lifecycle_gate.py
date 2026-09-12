#!/usr/bin/env python3
"""Activate navigation only after AMCL has produced a usable map TF.

The static map and AMCL can be started before an operator supplies the robot's
initial pose.  Nav2 global costmaps need ``map -> base_footprint`` during
activation, so activating the navigation lifecycle group on a fixed timer can
leave planner/controller nodes inactive forever.  This node keeps the group
manager idle until that transform exists, then requests STARTUP.  A failed
request is retried on the next timer tick.
"""

from __future__ import annotations

import rclpy
import tf2_ros
from nav2_msgs.srv import ManageLifecycleNodes
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.time import Time


class Nav2LifecycleGate(Node):
    """Wait for the AMCL transform before activating the Nav2 group."""

    def __init__(self) -> None:
        super().__init__("nav2_lifecycle_gate")
        self.declare_parameter("manager_service", "/lifecycle_manager_navigation/manage_nodes")
        self.declare_parameter("global_frame", "map")
        self.declare_parameter("base_frame", "base_footprint")
        self.declare_parameter("check_period_sec", 0.5)
        self.declare_parameter("tf_timeout_sec", 0.1)

        self._manager_service = str(self.get_parameter("manager_service").value)
        self._global_frame = str(self.get_parameter("global_frame").value)
        self._base_frame = str(self.get_parameter("base_frame").value)
        self._tf_timeout = float(self.get_parameter("tf_timeout_sec").value)
        period = max(float(self.get_parameter("check_period_sec").value), 0.1)

        self._tf_buffer = tf2_ros.Buffer()
        self._tf_listener = tf2_ros.TransformListener(self._tf_buffer, self)
        self._manager_client = self.create_client(
            ManageLifecycleNodes,
            self._manager_service,
        )
        self._timer = self.create_timer(period, self._tick)
        self._request_in_flight = False
        self._started = False
        self._last_wait_log = self.get_clock().now()
        self._last_failure_log = self.get_clock().now()

        self.get_logger().info(
            f"Waiting for {self._global_frame} -> {self._base_frame} "
            "before starting navigation lifecycle"
        )

    def _should_log(self, last_log) -> bool:
        return (self.get_clock().now() - last_log) >= Duration(seconds=5.0)

    def _has_map_tf(self) -> bool:
        try:
            self._tf_buffer.lookup_transform(
                self._global_frame,
                self._base_frame,
                Time(),
                timeout=Duration(seconds=self._tf_timeout),
            )
            return True
        except tf2_ros.TransformException:
            return False

    def _tick(self) -> None:
        if self._started or self._request_in_flight:
            return

        if not self._manager_client.service_is_ready():
            if self._should_log(self._last_wait_log):
                self._last_wait_log = self.get_clock().now()
                self.get_logger().info(f"Waiting for {self._manager_service}")
            return

        if not self._has_map_tf():
            if self._should_log(self._last_wait_log):
                self._last_wait_log = self.get_clock().now()
                self.get_logger().info(
                    "Waiting for map TF; set the robot pose with /initialpose "
                    "before navigation can start"
                )
            return

        request = ManageLifecycleNodes.Request()
        request.command = ManageLifecycleNodes.Request.STARTUP
        self._request_in_flight = True
        future = self._manager_client.call_async(request)
        future.add_done_callback(self._startup_done)

    def _startup_done(self, future) -> None:
        self._request_in_flight = False
        try:
            response = future.result()
        except Exception as error:  # service transport errors should be retryable
            if self._should_log(self._last_failure_log):
                self._last_failure_log = self.get_clock().now()
                self.get_logger().warning(f"Navigation lifecycle startup failed: {error}")
            return

        if response.success:
            self._started = True
            self._timer.cancel()
            self.get_logger().info("Navigation lifecycle is active after map TF became available")
            return

        if self._should_log(self._last_failure_log):
            self._last_failure_log = self.get_clock().now()
            self.get_logger().warning("Navigation lifecycle startup was rejected; retrying")


def main(args=None) -> None:
    rclpy.init(args=args)
    node = Nav2LifecycleGate()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
