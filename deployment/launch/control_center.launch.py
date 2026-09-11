"""Start the two isolated rosbridge websocket endpoints for T12 integration.

The control-center API is started by systemd (or start-backend.sh). Keeping
rosbridge in this launch description makes the two ROS domains explicit and
prevents accidentally sharing one bridge between robots.
"""
from __future__ import annotations

from launch import LaunchDescription
from launch.actions import ExecuteProcess


def generate_launch_description() -> LaunchDescription:
    return LaunchDescription([
        ExecuteProcess(
            cmd=["ros2", "run", "rosbridge_server", "rosbridge_websocket", "--port", "9090"],
            additional_env={"ROS_DOMAIN_ID": "12"},
            output="screen",
            name="rosbridge_robot_1",
        ),
        ExecuteProcess(
            cmd=["ros2", "run", "rosbridge_server", "rosbridge_websocket", "--port", "9091"],
            additional_env={"ROS_DOMAIN_ID": "13"},
            output="screen",
            name="rosbridge_robot_2",
        ),
    ])


if __name__ == "__main__":
    # ``ros2 launch`` accepts package launch files, while this repository's
    # deployment directory is deliberately not a ROS package.  Running the
    # Python launch file directly is therefore the portable invocation.
    from launch import LaunchService

    service = LaunchService()
    service.include_launch_description(generate_launch_description())
    raise SystemExit(service.run())
