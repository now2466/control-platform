from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, TimerAction
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description() -> LaunchDescription:
    use_sim_time = LaunchConfiguration("use_sim_time")
    autostart = LaunchConfiguration("autostart")
    params_file = LaunchConfiguration("params_file")
    map_file = LaunchConfiguration("map")
    log_level = LaunchConfiguration("log_level")

    tf_remappings = [("/tf", "tf"), ("/tf_static", "tf_static")]
    velocity_remappings = [*tf_remappings, ("cmd_vel", "/control/nav_velocity")]

    localization_nodes = [
        Node(
            package="nav2_map_server",
            executable="map_server",
            name="map_server",
            output="screen",
            arguments=["--ros-args", "--log-level", log_level],
            parameters=[params_file, {"use_sim_time": use_sim_time, "yaml_filename": map_file}],
            remappings=tf_remappings,
        ),
        Node(
            package="nav2_amcl",
            executable="amcl",
            name="amcl",
            output="screen",
            arguments=["--ros-args", "--log-level", log_level],
            parameters=[
                params_file,
                {
                    "use_sim_time": use_sim_time,
                    "set_initial_pose": False,
                    "autostart": autostart,
                },
            ],
            remappings=tf_remappings,
        ),
    ]
    localization_manager = Node(
        package="nav2_lifecycle_manager",
        executable="lifecycle_manager",
        name="lifecycle_manager_localization",
        output="screen",
        parameters=[
            {
                "use_sim_time": use_sim_time,
                "autostart": autostart,
                "node_names": ["map_server", "amcl"],
            }
        ],
    )

    navigation_nodes = [
        Node(
            package="nav2_controller",
            executable="controller_server",
            name="controller_server",
            output="screen",
            arguments=["--ros-args", "--log-level", log_level],
            parameters=[params_file, {"use_sim_time": use_sim_time, "autostart": autostart}],
            remappings=velocity_remappings,
        ),
        Node(
            package="nav2_planner",
            executable="planner_server",
            name="planner_server",
            output="screen",
            arguments=["--ros-args", "--log-level", log_level],
            parameters=[params_file, {"use_sim_time": use_sim_time, "autostart": autostart}],
            remappings=tf_remappings,
        ),
        Node(
            package="nav2_behaviors",
            executable="behavior_server",
            name="behavior_server",
            output="screen",
            arguments=["--ros-args", "--log-level", log_level],
            parameters=[params_file, {"use_sim_time": use_sim_time, "autostart": autostart}],
            remappings=velocity_remappings,
        ),
        Node(
            package="nav2_bt_navigator",
            executable="bt_navigator",
            name="bt_navigator",
            output="screen",
            arguments=["--ros-args", "--log-level", log_level],
            parameters=[
                params_file,
                {
                    "use_sim_time": use_sim_time,
                    "autostart": autostart,
                    "robot_base_frame": "base_footprint",
                },
            ],
            remappings=tf_remappings,
        ),
        Node(
            package="nav2_waypoint_follower",
            executable="waypoint_follower",
            name="waypoint_follower",
            output="screen",
            arguments=["--ros-args", "--log-level", log_level],
            parameters=[params_file, {"use_sim_time": use_sim_time, "autostart": autostart}],
            remappings=tf_remappings,
        ),
    ]
    navigation_manager = Node(
        package="nav2_lifecycle_manager",
        executable="lifecycle_manager",
        name="lifecycle_manager_navigation",
        output="screen",
        parameters=[
            {
                "use_sim_time": use_sim_time,
                "autostart": autostart,
                "node_names": [
                    "controller_server",
                    "planner_server",
                    "behavior_server",
                    "bt_navigator",
                    "waypoint_follower",
                ],
            }
        ],
    )

    return LaunchDescription(
        [
            DeclareLaunchArgument("use_sim_time", default_value="false"),
            DeclareLaunchArgument("autostart", default_value="true"),
            DeclareLaunchArgument(
                "params_file",
                default_value=PathJoinSubstitution(
                    [FindPackageShare("pinky_control_navigation"), "params", "nav2_params.yaml"]
                ),
            ),
            DeclareLaunchArgument(
                "map",
                default_value=PathJoinSubstitution(
                    [FindPackageShare("pinky_control_navigation"), "map", "map_260905.yaml"]
                ),
            ),
            DeclareLaunchArgument("log_level", default_value="info"),
            *localization_nodes,
            localization_manager,
            # Let map_server/amcl reach ACTIVE before costmaps configure.
            TimerAction(
                period=2.0,
                actions=[*navigation_nodes, navigation_manager],
            ),
        ]
    )
