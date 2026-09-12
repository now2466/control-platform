#!/usr/bin/env bash

# Start every robot-side process required for the robot_2 control-center test.
# Run this once, in one SSH terminal, after the robot has finished booting.

set -Eeo pipefail

PINKY_PRO_WS="${PINKY_PRO_WS:-/home/pinky/pinky_pro}"
PINKY_CONTROL_WS="${PINKY_CONTROL_WS:-/home/pinky/dev_ws/wj}"
ROBOT_SESSION_SCRIPT="${ROBOT_SESSION_SCRIPT:-/home/pinky/start-pinky-robot2-session.sh}"
ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-13}"
START_NAV2="${START_NAV2:-1}"

bringup_pid=""
session_pid=""
cleanup_done=0

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

stop_process_group() {
  local pid="$1"

  [[ -n "$pid" ]] || return 0
  kill -0 "$pid" 2>/dev/null || return 0
  kill -INT -- "-$pid" 2>/dev/null || kill -INT "$pid" 2>/dev/null || true
}

wait_for_exit() {
  local pid="$1"
  local attempt

  [[ -n "$pid" ]] || return 0
  for ((attempt = 1; attempt <= 15; attempt++)); do
    kill -0 "$pid" 2>/dev/null || return 0
    sleep 1
  done
  return 1
}

cleanup() {
  [[ "$cleanup_done" -eq 0 ]] || return
  cleanup_done=1
  set +e

  if [[ -n "$session_pid" ]]; then
    echo "Stopping robot_2 control session..."
    stop_process_group "$session_pid"
    wait_for_exit "$session_pid" || true
  fi

  if [[ -n "$bringup_pid" ]]; then
    echo "Stopping Pinky hardware bringup..."
    stop_process_group "$bringup_pid"
    wait_for_exit "$bringup_pid" || true
  fi

  wait "$session_pid" "$bringup_pid" 2>/dev/null || true
}

wait_for_publisher() {
  local topic="$1"
  local owner_pid="$2"
  local timeout_seconds="${3:-45}"
  local attempt
  local topic_info

  for ((attempt = 1; attempt <= timeout_seconds; attempt++)); do
    kill -0 "$owner_pid" 2>/dev/null || return 1
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
  local owner_pid="$2"
  local timeout_seconds="${3:-75}"
  local attempt
  local action_list

  for ((attempt = 1; attempt <= timeout_seconds; attempt++)); do
    kill -0 "$owner_pid" 2>/dev/null || return 1
    action_list="$(timeout 5s ros2 action list -t 2>/dev/null || true)"
    if grep -Eq "^${action}[[:space:]]" <<<"$action_list"; then
      return 0
    fi
    sleep 1
  done
  return 1
}

trap cleanup EXIT
trap 'exit 130' INT TERM
trap 'exit 129' HUP

# ROS setup scripts read variables that may not exist. Enable nounset only
# after sourcing the underlay and both overlays.
[[ -f /opt/ros/jazzy/setup.bash ]] || fail "missing ROS Jazzy setup"
[[ -f "$PINKY_PRO_WS/install/setup.bash" ]] || fail "missing Pinky Pro workspace setup"
[[ -f "$PINKY_CONTROL_WS/install/setup.bash" ]] || fail "missing control workspace setup"
source /opt/ros/jazzy/setup.bash
source "$PINKY_PRO_WS/install/setup.bash"
source "$PINKY_CONTROL_WS/install/setup.bash"
set -u

unset ROS_LOCALHOST_ONLY
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
export ROS_DOMAIN_ID
export ROS2CLI_NO_DAEMON=1
export START_NAV2

[[ "$ROS_DOMAIN_ID" == "13" ]] || fail "robot_2 must run with ROS_DOMAIN_ID=13"
[[ -x "$ROBOT_SESSION_SCRIPT" ]] || fail "missing executable $ROBOT_SESSION_SCRIPT"
command -v ros2 >/dev/null || fail "ros2 is not available after sourcing ROS Jazzy"
ros2 pkg prefix pinky_bringup >/dev/null || fail "pinky_bringup is not available"
if [[ "$START_NAV2" == "1" ]]; then
  ros2 pkg prefix pinky_control_navigation >/dev/null || fail "pinky_control_navigation is not available"
elif [[ "$START_NAV2" != "0" ]]; then
  fail "START_NAV2 must be 0 or 1"
fi

echo "Stopping boot-time domain-0 services if they are active..."
systemctl --user stop rosy-session-control.service 2>/dev/null || true
systemctl --user stop rosy-session-bringup.service 2>/dev/null || true

existing_bringup="$(pgrep -u "$(id -un)" -f '[r]os2 launch pinky_bringup bringup_robot.launch.xml' || true)"
[[ -z "$existing_bringup" ]] || fail "Pinky bringup is already running (PID(s): $existing_bringup)"

existing_session="$(pgrep -u "$(id -un)" -f '[s]tart-pinky-robot2-session.sh' || true)"
[[ -z "$existing_session" ]] || fail "robot_2 session is already running (PID(s): $existing_session)"

echo "Starting Pinky hardware bringup (ROS_DOMAIN_ID=$ROS_DOMAIN_ID)..."
setsid ros2 launch pinky_bringup bringup_robot.launch.xml &
bringup_pid=$!

wait_for_publisher /odom "$bringup_pid" 45 || fail "hardware bringup did not publish /odom"
wait_for_publisher /scan "$bringup_pid" 45 || fail "hardware bringup did not publish /scan"
echo "Hardware bringup is ready (/odom and /scan)."

echo "Starting rosbridge, watchdog, Nav2 and camera..."
setsid "$ROBOT_SESSION_SCRIPT" &
session_pid=$!

wait_for_publisher /control/status "$session_pid" 30 || fail "watchdog did not publish /control/status"
wait_for_publisher /camera/image_raw/compressed "$session_pid" 60 || fail "camera did not publish compressed frames"
if [[ "$START_NAV2" == "1" ]]; then
  wait_for_action_server /navigate_to_pose "$session_pid" 90 || fail "Nav2 action server did not become ready"
fi

echo
echo "Robot_2 all-in-one session is ready."
echo "  domain:     $ROS_DOMAIN_ID"
echo "  odometry:   /odom"
echo "  lidar:      /scan"
echo "  rosbridge:  ws://0.0.0.0:9091"
echo "  camera:     /camera/image_raw/compressed"
echo "  navigation: $START_NAV2 (/navigate_to_pose)"
echo "Set the initial pose in the web UI after every reboot."
echo "Press Ctrl+C once to stop the complete robot-side session."

# If either supervisor exits unexpectedly, stop the other side as well.
wait -n "$bringup_pid" "$session_pid"
