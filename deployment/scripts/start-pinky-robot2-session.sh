#!/usr/bin/env bash

# Start the robot-side processes required by the control center for robot_2.
# The hardware bringup is intentionally left outside this script: run
# bringup_robot.launch.xml in its own terminal and keep the robot stationary
# while starting or stopping this session.

set -Eeo pipefail

PINKY_WS="${PINKY_WS:-/home/pinky/dev_ws/wj}"
ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-13}"
ROSBRIDGE_PORT="${ROSBRIDGE_PORT:-9091}"
START_NAV2="${START_NAV2:-1}"
CONFIG_DIR="$PINKY_WS/install/rosy_control/share/rosy_control/config"

CAMERA_TOPIC="/camera/front"
COMPRESSED_TOPIC="/camera/image_raw/compressed"
CONTROL_STATUS_TOPIC="/control/status"

camera_pid=""
republisher_pid=""
rosbridge_pid=""
watchdog_pid=""
nav2_pid=""
cleanup_done=0
camera_library_path=""

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

cleanup() {
  [[ "$cleanup_done" -eq 0 ]] || return
  cleanup_done=1
  set +e
  for pid in "$nav2_pid" "$republisher_pid" "$camera_pid" "$watchdog_pid" "$rosbridge_pid"; do
    if [[ -n "$pid" ]]; then
      # Each process is started in its own session so ros2run's child (for
      # example the Python rosbridge server) is stopped together with it.
      kill -INT -- "-$pid" 2>/dev/null || kill -INT "$pid" 2>/dev/null
    fi
  done
  wait "$nav2_pid" "$republisher_pid" "$camera_pid" "$watchdog_pid" "$rosbridge_pid" 2>/dev/null || true
}

wait_for_publisher() {
  local topic="$1"
  local pid="$2"
  local timeout_seconds="${3:-30}"
  local attempt
  local topic_info

  for ((attempt = 1; attempt <= timeout_seconds; attempt++)); do
    if ! kill -0 "$pid" 2>/dev/null; then
      return 1
    fi
    topic_info="$(timeout 5s ros2 topic info "$topic" 2>/dev/null || true)"
    if grep -Eq 'Publisher count: [1-9]' <<<"$topic_info"; then
      return 0
    fi
    sleep 1
  done
  return 1
}

wait_for_action_server() {
  local action="$1"
  local pid="$2"
  local timeout_seconds="${3:-30}"
  local attempt
  local action_info

  for ((attempt = 1; attempt <= timeout_seconds; attempt++)); do
    if ! kill -0 "$pid" 2>/dev/null; then
      return 1
    fi
    action_info="$(timeout 5s ros2 action list -t 2>/dev/null || true)"
    if grep -Eq "^${action}[[:space:]]" <<<"$action_info"; then
      return 0
    fi
    sleep 1
  done
  return 1
}

start_lidar_motor() {
  local attempt
  local services

  echo "Starting SLLidar motor..."
  for ((attempt = 1; attempt <= 15; attempt++)); do
    services="$(timeout 5s ros2 service list 2>/dev/null || true)"
    if grep -Fxq "/start_motor" <<<"$services"; then
      if timeout 10s ros2 service call /start_motor std_srvs/srv/Empty "{}" >/dev/null 2>&1; then
        echo "SLLidar motor is running."
        return 0
      fi
    fi
    sleep 1
  done
  fail "SLLidar /start_motor service did not become ready; /scan and map TF cannot be produced"
}

trap cleanup EXIT
trap 'exit 130' INT TERM

source /opt/ros/jazzy/setup.bash
source "$PINKY_WS/install/setup.bash"

# ROS setup scripts legitimately read variables that may not exist yet.
# Enable nounset only after both underlay and overlay have been sourced.
set -u

camera_library_path="${PINKY_CAMERA_LD_LIBRARY_PATH:-${LD_LIBRARY_PATH:-}}"
if [[ -f /usr/local/lib/aarch64-linux-gnu/libpisp.so.1 ]]; then
  # camera_detect_node uses the Raspberry Pi libcamera 0.3.x Python stack.
  # ROS Jazzy also ships libpisp, but its ABI is not compatible with the
  # /usr/local libcamera IPA module on this robot. Prefer the matching local
  # camera libraries for this process only while retaining the ROS paths.
  camera_library_path="/usr/local/lib/aarch64-linux-gnu:/usr/local/lib:$camera_library_path"
fi

unset ROS_LOCALHOST_ONLY
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
export ROS_DOMAIN_ID
export PATH="/usr/bin:/bin:$PATH"

[[ -f "$CONFIG_DIR/robot.yaml" ]] || fail "missing $CONFIG_DIR/robot.yaml"
[[ -f "$CONFIG_DIR/camera.yaml" ]] || fail "missing $CONFIG_DIR/camera.yaml"
command -v ros2 >/dev/null || fail "ros2 is not available after sourcing ROS Jazzy"
ros2 pkg prefix rosy_control >/dev/null || fail "rosy_control package is not available"
ros2 pkg prefix image_transport >/dev/null || fail "image_transport package is not available"
ros2 pkg prefix rosbridge_server >/dev/null || fail "rosbridge_server package is not available"
ros2 pkg prefix pinky_control_watchdog >/dev/null || fail "pinky_control_watchdog package is not available; build the control workspace first"
if [[ "$START_NAV2" == "1" ]]; then
  ros2 pkg prefix pinky_control_navigation >/dev/null || fail "pinky_control_navigation package is not available; build the control workspace first"
elif [[ "$START_NAV2" != "0" ]]; then
  fail "START_NAV2 must be 0 or 1"
fi

if systemctl --user is-active --quiet rosy-session-control.service; then
  echo "Stopping rosy-session-control.service to avoid duplicate camera nodes..."
  systemctl --user stop rosy-session-control.service
fi

existing_camera="$(pgrep -u "$(id -un)" -f '[/]rosy_control/camera_detect_node' || true)"
[[ -z "$existing_camera" ]] || fail "camera_detect_node is already running (PID(s): $existing_camera)"

existing_republisher="$(pgrep -u "$(id -un)" -f '[i]mage_transport republish raw compressed' || true)"
[[ -z "$existing_republisher" ]] || fail "image republisher is already running (PID(s): $existing_republisher)"

existing_watchdog="$(pgrep -u "$(id -un)" -f '[/]pinky_control_watchdog/manual_velocity_watchdog' || true)"
[[ -z "$existing_watchdog" ]] || fail "pinky control watchdog is already running (PID(s): $existing_watchdog)"

existing_bridge="$(pgrep -u "$(id -un)" -f "[r]osbridge_websocket.*--port.*${ROSBRIDGE_PORT}" || true)"
[[ -z "$existing_bridge" ]] || fail "rosbridge is already running on port $ROSBRIDGE_PORT (PID(s): $existing_bridge)"

echo "Starting rosbridge on port $ROSBRIDGE_PORT (ROS_DOMAIN_ID=$ROS_DOMAIN_ID)..."
setsid ros2 run rosbridge_server rosbridge_websocket --port "$ROSBRIDGE_PORT" &
rosbridge_pid=$!

echo "Starting Pinky control watchdog..."
setsid ros2 run pinky_control_watchdog manual_velocity_watchdog --ros-args \
  -p robot_id:=robot_2 \
  -p manual_topic:=/control/manual_velocity \
  -p nav_topic:=/control/nav_velocity \
  -p navigate_action_name:=/navigate_to_pose \
  -p cmd_vel_topic:=/cmd_vel \
  -p status_topic:="$CONTROL_STATUS_TOPIC" \
  -p heartbeat_topic:=/control/heartbeat \
  -p max_linear_mps:=0.15 \
  -p max_angular_rps:=0.50 &
watchdog_pid=$!

if ! wait_for_publisher "$CONTROL_STATUS_TOPIC" "$watchdog_pid" 15; then
  fail "control watchdog did not publish $CONTROL_STATUS_TOPIC within 15 seconds"
fi

if [[ "$START_NAV2" == "1" ]]; then
  start_lidar_motor
  echo "Starting Pinky Nav2 on map_260905..."
  setsid ros2 launch pinky_control_navigation robot_nav2.launch.py use_sim_time:=false &
  nav2_pid=$!
  if ! wait_for_action_server "/navigate_to_pose" "$nav2_pid" 60; then
    fail "Nav2 did not expose /navigate_to_pose within 60 seconds"
  fi
else
  echo "Nav2 is disabled (set START_NAV2=1 after building pinky_control_navigation)."
fi

echo "Starting Pinky camera publisher..."
setsid env "LD_LIBRARY_PATH=$camera_library_path" ros2 run rosy_control camera_detect_node --ros-args \
  --params-file "$CONFIG_DIR/robot.yaml" \
  --params-file "$CONFIG_DIR/camera.yaml" &
camera_pid=$!

if ! wait_for_publisher "$CAMERA_TOPIC" "$camera_pid" 30; then
  fail "camera publisher did not publish $CAMERA_TOPIC within 30 seconds"
fi

echo "Starting raw-to-compressed image republisher..."
setsid ros2 run image_transport republish raw compressed --ros-args \
  -p in_transport:=raw \
  -p out_transport:=compressed \
  -r in:="$CAMERA_TOPIC" \
  -r out/compressed:="$COMPRESSED_TOPIC" &
republisher_pid=$!

if ! wait_for_publisher "$COMPRESSED_TOPIC" "$republisher_pid" 30; then
  fail "compressed image publisher did not publish $COMPRESSED_TOPIC within 30 seconds"
fi

echo "Robot_2 session is ready."
echo "  ROS_DOMAIN_ID: $ROS_DOMAIN_ID"
echo "  rosbridge:     ws://0.0.0.0:$ROSBRIDGE_PORT"
echo "  camera:        $CAMERA_TOPIC"
echo "  compressed:     $COMPRESSED_TOPIC"
echo "  control:       /control/manual_velocity -> /cmd_vel (watchdog)"
echo "  navigation:    ${START_NAV2} (/navigate_to_pose -> /control/nav_velocity)"
echo "Press Ctrl+C to stop this session. Hardware bringup is not stopped."

session_pids=("$rosbridge_pid" "$camera_pid" "$watchdog_pid" "$republisher_pid")
[[ -n "$nav2_pid" ]] && session_pids+=("$nav2_pid")
wait -n "${session_pids[@]}"
exit $?
