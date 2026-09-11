# T12 — rosbridge ROS 2 연동 TDD 기록

## RED

`backend/tests/test_rosbridge_adapter.py`를 먼저 추가해 다음 계약을 고정했다.

- `robot_1`의 domain은 12, `robot_2`의 domain은 13이며 endpoint도 서로 달라야 한다.
- 구독과 control service call은 각 robot ID에 설정된 websocket으로만 전송된다.
- rosbridge `CompressedImage` JSON/base64는 JPEG frame으로 변환한다.
- `Odometry`는 확인되지 않은 공통 map pose로 승격하지 않는다. map TF가 검증되기 전 `MAP_TF_UNVERIFIED`다.
- endpoint가 없어도 ROS 모드는 관찰 모드로 시작해 OFFLINE/STALE 상태를 표시하며, mock 설정을 하드웨어에 적용했다고 주장하지 않는다.
- fragmented camera publish, cross-robot service response, stale pose 뒤 battery update, sensor overlay 미구현을 regression test로 고정했다.

## GREEN

`RosbridgeAdapter`는 `robots.ros.yaml`의 고정 robot/domain/endpoint mapping으로 websocket worker 두 개를 시작한다. 각 worker는 odom, battery, control status, compressed camera, path를 구독하고 1/2/4/8초 backoff로 재연결한다. fragment는 최대 64개·4 MiB·5초로 reassemble하며, response는 요청한 robot의 같은 socket에서만 받아 command event로 변환한다. 전송 중 하나가 끊겨도 다른 robot의 socket으로 command가 바뀌지 않고 해당 camera cache를 폐기한다.

현재 `pinky_control_interfaces`의 `ControlCommand`/`FollowCommand` 계약은 실제 로봇 저장소에 없으므로 기본 설정의 `control_available`/`follow_available`은 false다. adapter는 직접 `/cmd_vel`을 발행하지 않으며 이 상태의 제어 요청은 `UNSUPPORTED`다.

## 검증

```text
cd backend && .venv/bin/python -m pytest tests/test_rosbridge_adapter.py tests/test_contracts.py tests/test_cameras.py tests/test_state.py -q
```

결과: 18 passed (2026-09-11).
