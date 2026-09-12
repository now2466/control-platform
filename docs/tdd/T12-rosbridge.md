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

`RosbridgeAdapter`는 `robots.ros.yaml`의 고정 robot/domain/endpoint mapping으로 websocket worker 두 개를 시작한다. 각 worker는 odom, battery, control status, compressed camera, path를 구독하고 1/2/4/8초 backoff로 재연결한다. fragment는 최대 16 active ID·64개/ID·4 MiB/ID·5초로 reassemble하며, response는 요청한 robot의 같은 socket에서만 받아 command event로 변환한다. disconnect는 pose/battery/camera timestamp와 cached frame을 폐기하므로 reconnect가 old telemetry를 FRESH로 되살리지 않는다. camera는 2초 동안 새 frame이 없으면 STALE이다.

`wss://` endpoint에는 security mapping의 `ca_cert_env`, `client_cert_env`/`client_key_env`, `authorization_token_env`를 선택적으로 지정할 수 있다. YAML에는 secret이나 certificate contents가 아닌 environment variable 이름만 저장한다. TLS verification은 기본 활성이고 client certificate/key는 쌍으로만 허용한다.

`RosbridgeAdapter`는 `/tf`·`/tf_static`과 odom을 함께 받아 `map → odom → base`를 2D로 합성하고, 검증된 경우에만 공통 map 좌표로 상태를 노출한다. 초기 위치는 정지 조건을 통과한 뒤 설정한 initial pose 토픽(실물 Pinky `/initialpose`)에 `PoseWithCovarianceStamped`로 발행하며, 수동 속도는 설정한 중재 토픽(실물 Pinky `/control/manual_velocity`)으로만 발행한다. 최종 `/cmd_vel`은 로봇 측 안전 중재기가 담당한다.

robot_2 실물 카메라 smoke 절차는 `deployment/scripts/start-pinky-robot2-session.sh`로 고정한다. bringup은 별도로 유지하고, 스크립트가 domain 13의 `camera_detect_node` `/camera/front`, `image_transport` raw→compressed 변환, rosbridge `9091`을 하나의 수명 주기로 관리한다. 시작 전 중복 camera/republisher/rosbridge를 거부하며, 원본 publisher와 compressed publisher가 각각 나타난 뒤에만 READY를 출력한다.

`ros/pinky_control_interfaces`의 `ControlCommand`와 `ControlStatus`, `ros/pinky_control_watchdog`의 단일 출력 중재기를 추가했다. `ControlCommand` 요청은 `command_id`, `operation`, `parameters_json` 필드를 사용한다. 중재기는 startup stop latch, `reset_stop` 후 자동 재개 금지, `MANUAL` mode gate, 0.35초 deadman, 0.15m/s·0.50rad/s clamp를 적용하고 `/cmd_vel`에 `Twist`만 발행한다. 서버가 설치되지 않은 환경의 주행·편대 제어 요청은 계속 `UNSUPPORTED`다. robot_2 local deployment만 설치·무이동 확인 뒤 `control_available=true`로 전환한다.

## 검증

```text
cd backend && .venv/bin/python -m pytest tests/test_rosbridge_adapter.py tests/test_contracts.py tests/test_cameras.py tests/test_state.py -q
```

결과: 29 passed (2026-09-12).

로봇에서 실행할 정적 검증:

```text
bash -n deployment/scripts/start-pinky-robot2-session.sh
```

로봇 workspace 설치 후에는 다음을 무이동 상태에서 확인한다.

```text
colcon build --symlink-install --packages-select pinky_control_interfaces pinky_control_watchdog
ros2 topic info /control/status -v
ros2 service type /control/command
ros2 topic info /cmd_vel -v
```

이후 `reset_stop`·`set_mode(MANUAL)` 응답, 수동 입력 중 `/cmd_vel`, 입력 중단 0.35초 이내 정지를 확인한 뒤에만 바퀴를 지면에 둔 저속 시험으로 진행한다.
