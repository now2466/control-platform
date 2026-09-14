# T12 — rosbridge ROS 2 연동 TDD 기록

## RED

`backend/tests/test_rosbridge_adapter.py`를 먼저 추가해 다음 계약을 고정했다.

- `robot_1`의 domain은 12, `robot_2`의 domain은 13이며 endpoint도 서로 달라야 한다.
- 구독과 control service call은 각 robot ID에 설정된 websocket으로만 전송된다.
- rosbridge `CompressedImage` JSON/base64는 JPEG frame으로 변환한다.
- `Odometry`는 확인되지 않은 공통 map pose로 승격하지 않는다. map TF가 검증되기 전 `MAP_TF_UNVERIFIED`다.
- endpoint가 없어도 ROS 모드는 관찰 모드로 시작해 OFFLINE/STALE 상태를 표시하며, mock 설정을 하드웨어에 적용했다고 주장하지 않는다.
- fragmented camera publish, cross-robot service response, stale pose 뒤 battery update, sensor overlay 미구현을 regression test로 고정했다.
- disconnect/reconnect 뒤 old telemetry 격리, odom이 계속 와도 2초 뒤 camera STALE 전이, fragment ID 상한, event stream close, TLS/token environment reference를 추가로 고정했다.
- camera가 STALE이면 cached JPEG도 전달하지 않는 것, disconnect가 mode/stop latch/capability/path 같은 live control state를 비우는 것, ROS Path가 200 point 이하 snapshot과 layer event에 함께 반영되는 것을 고정했다.

## GREEN

`RosbridgeAdapter`는 `robots.ros.yaml`의 고정 robot/domain/endpoint mapping으로 websocket worker 두 개를 시작한다. 각 worker는 odom, battery, control status, path를 구독하며, `camera.enabled=true`인 로봇만 compressed camera를 추가 구독하고 1/2/4/8초 backoff로 재연결한다. fragment는 최대 16 active ID·64개/ID·4 MiB/ID·5초로 reassemble하며, response는 요청한 robot의 같은 socket에서만 받아 command event로 변환한다. disconnect는 pose/battery/camera timestamp와 cached frame을 폐기하므로 reconnect가 old telemetry를 FRESH로 되살리지 않는다. camera는 2초 동안 새 frame이 없으면 STALE이다.

`wss://` endpoint에는 security mapping의 `ca_cert_env`, `client_cert_env`/`client_key_env`, `authorization_token_env`를 선택적으로 지정할 수 있다. YAML에는 secret이나 certificate contents가 아닌 environment variable 이름만 저장한다. TLS verification은 기본 활성이고 client certificate/key는 쌍으로만 허용한다.

`RosbridgeAdapter`는 `/tf`·`/tf_static`과 odom을 함께 받아 `map → odom → base`를 2D로 합성하고, 검증된 경우에만 공통 map 좌표로 상태를 노출한다. 초기 위치는 정지 조건을 통과한 뒤 설정한 initial pose 토픽(실물 Pinky `/initialpose`)에 `PoseWithCovarianceStamped`로 발행하며, 수동 속도는 설정한 중재 토픽(실물 Pinky `/control/manual_velocity`)으로만 발행한다. 지도 주행은 start pose를 먼저 발행하고 `AUTO`와 `navigate` ControlCommand를 요청한다. 최종 `/cmd_vel`은 로봇 측 안전 중재기가 담당한다.

robot_2 실물 Nav2 smoke 절차는 `deployment/scripts/start-pinky-robot2-session.sh`로 고정한다. bringup은 별도로 유지하고, `START_NAV2=1`이면 스크립트가 먼저 `/start_motor`로 SLLidar를 시작한 뒤 Nav2와 rosbridge `9091`을 하나의 수명 주기로 관리한다. YYM 현장 프로필에서는 카메라 publisher와 republisher를 시작하지 않는다.

재부팅 후 기본 smoke 진입점은 `deployment/scripts/start-pinky-robot2-all.sh`다. wrapper는 domain 0의 기존 user service를 중지하고 domain 13 hardware bringup에서 `/odom`과 `/scan` publisher를 확인한 뒤 위 session script를 시작한다. `/navigate_to_pose` action을 확인하기 전에는 all-in-one READY를 출력하지 않는다. wrapper의 `Ctrl+C` cleanup은 session을 먼저 종료하고 bringup을 나중에 종료한다. 기존 session script 단독 실행은 bringup/session 분리 진단용으로 유지한다.

`ros/pinky_control_interfaces`의 `ControlCommand`와 `ControlStatus`, `ros/pinky_control_watchdog`의 단일 출력 중재기를 추가했다. `ControlCommand` 요청은 `command_id`, `operation`, `parameters_json` 필드를 사용한다. 중재기는 startup stop latch, `reset_stop` 후 자동 재개 금지, `MANUAL` mode gate, 0.35초 deadman, 0.15m/s·0.50rad/s clamp를 적용하고 `/cmd_vel`에 `Twist`만 발행한다. `navigate`는 Nav2 `NavigateToPose` action client로 연결하고 stop/reset/cancel 시 활성 goal을 취소한다. `ros/pinky_control_navigation`은 `map_260905.world`와 동일한 정적 map server/AMCL/Nav2 구성을 제공하며, navigation lifecycle은 고정 지연 대신 AMCL의 `map→base_footprint` TF를 확인한 뒤 startup을 재시도한다. 서버가 설치되지 않은 환경의 주행·편대 제어 요청은 계속 `UNSUPPORTED`다. robot_2 local deployment만 설치·무이동 확인 뒤 `control_available=true`로 전환한다.

## 검증

```text
cd backend && .venv/bin/python -m pytest tests/test_rosbridge_adapter.py tests/test_contracts.py tests/test_cameras.py tests/test_state.py -q
```

결과: 29 passed (2026-09-12).

로봇에서 실행할 정적 검증:

```text
bash -n deployment/scripts/start-pinky-robot2-session.sh
bash -n deployment/scripts/start-pinky-robot2-all.sh
```

로봇 workspace 설치 후에는 다음을 무이동 상태에서 확인한다.

hardware bringup(`pinky_bringup`, `sllidar_ros2`)은 `~/pinky_pro`에서, control
watchdog·Nav2 session은 `~/dev_ws/wj`에서 각각 source한다. `pinky_pro`를
`wj` 위에 다시 source해 overlay를 덮어쓰지 않는다.

```text
colcon build --symlink-install --packages-select pinky_control_interfaces pinky_control_watchdog pinky_control_navigation
ros2 topic info /control/status -v
ros2 service type /control/command
ros2 topic info /cmd_vel -v
ros2 action list -t | grep navigate_to_pose
ros2 lifecycle get /amcl
ros2 lifecycle get /planner_server
ros2 lifecycle get /bt_navigator
```

이후 `reset_stop`·`set_mode(MANUAL)` 응답, 수동 입력 중 `/cmd_vel`, 입력 중단 0.35초 이내 정지, `navigate` capability와 `/navigate_to_pose` action server를 무이동 상태에서 확인한다. 초기 위치를 보낸 뒤 `map→odom→base_footprint` TF와 `/planner_server`, `/bt_navigator`의 ACTIVE를 확인한 뒤에만 바퀴를 지면에 둔 저속 시험으로 진행한다. 로봇을 들어 옮긴 뒤에는 정지 확인 → 새 시작점 지정 → `localization-reset`/AMCL → TF 대기 → 명시적 정지 해제 → 새 도착점 요청 순서를 지킨다. 정적 지도는 초기화하지 않는다.
