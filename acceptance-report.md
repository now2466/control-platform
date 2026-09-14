# T14/T15 통합·인수 기록

작성일: 2026-09-12  ·  기준: `dev`  ·  영상 녹화/재생(T11): 제외

이 문서는 mock에서 재현 가능한 수용 증거와 ROS/Gazebo 현장 검증을 분리해 기록한다. `PASS`는 실행 증거가 저장된 항목, `PARTIAL`은 요구 증거 중 일부만 확인한 항목, `FAIL`은 assertion 또는 계약 위반, `NOT_RUN`은 ROS·하드웨어 전제가 없어 실행하지 않은 항목이다.

## Mock smoke

실행 명령:

```bash
deployment/scripts/acceptance.sh
```

| 시나리오 | 결과 | 증거 |
|---|---|---|
| A01 두 로봇·지도·두 JPEG 카메라 | PASS | `backend/tests/test_t14_acceptance.py::test_a01_mock_dashboard_has_two_robots_map_and_two_camera_streams` |
| A02 목표·편대·도착 | PASS | 기존 `backend/tests/test_t06_mission.py`, `test_t07_patrol.py` |
| A03 추종 준비 거절 | PASS | 기존 `backend/tests/test_t06_mission.py` |
| A04 전체 정지·슬레이브 무응답 | PASS | `test_a04_stop_preserves_offline_robot_as_unconfirmed_candidate` |
| A05 수동 watchdog/포커스·연결 종료 | PASS | 기존 `backend/tests/test_safety.py`, frontend `T05.test.tsx` |
| A06 추종 상실 | PASS | `test_a06_a07_failure_injection_is_scoped_to_formation_or_camera` |
| A07 카메라 한 대 중단 | PASS | 같은 test의 robot_2 `503`, robot_1 `200` assertion |
| A08 중복 request_id | PASS | `test_a08_duplicate_request_id_does_not_create_a_second_command` |
| N09 HTTPS Secure cookie | PASS | `test_n09_secure_cookie_switch_is_explicit` |
| A17 지도 클릭 주행·수동 재배치 후 AMCL 재설정 | PASS | `backend/tests/test_t15_map_navigation.py`, `frontend/src/MapPanel.test.tsx` |

## ROS/Gazebo gate

아래는 T12 어댑터와 현장 장비가 준비될 때 실행한다. 실행 전 `deployment/robots.ros.example.yaml`에 실제 bridge 주소·토픽·타입을 기록하고, 토큰은 환경에서 주입한다.

| 요구사항/시험 | 상태 | 필요한 증거 |
|---|---|---|
| robot_1 domain 12 / bridge 9090 | PASS | 2026-09-14 `192.168.0.8` hardware bringup, PC rosbridge `127.0.0.1:9090`, 플랫폼 `ONLINE` 및 odom·배터리 FRESH, scan/TF 구독 확인 |
| robot_2 domain 13 / bridge 9091 | PASS | 2026-09-12 rosbridge client 연결, `/odom`·배터리·TF·카메라 구독 및 웹 실영상 확인 |
| 두 namespace의 TF 경로와 공통 map 좌표 | NOT_RUN | `tf2_tools view_frames`, 시간 동기 상태 |
| compressed camera topic 매핑·두 스트림·실제 FPS/p95 | PARTIAL | 2026-09-14 robot_2 `/camera/image_raw/compressed` publisher 1개와 플랫폼 JPEG HTTP 200 확인. robot_1 카메라/control workspace 미설치, 두 스트림 장기 FPS/p95 미측정 |
| control/follow 수락·결과·재연결 | NOT_RUN | command_id 로그와 adapter contract test |
| stop latch·watchdog·최종 cmd_vel 단일 중재 | NOT_RUN | 로봇 측 출력 0 및 래치 증거 |
| robot_2 control/watchdog/navigation 패키지 build | PASS | 2026-09-12 `/home/pinky/dev_ws/wj`에서 3개 패키지 `colcon build` 통과 |
| `/navigate_to_pose` action·AMCL lifecycle·정적 map server | PASS | 2026-09-12 action server 1개, AMCL/map/planner/controller active 및 마지막 goal status 4 `SUCCEEDED` 확인 |
| `map→odom→base_footprint` 및 라이다 costmap 반영 | PARTIAL | 갱신되는 TF와 `/scan` publisher 1개·약 10Hz 확인. 실제 장애물 costmap 반영은 미확인 |
| 지도 시작점→AMCL→AUTO→목표 저속 주행 | PARTIAL | 실제 이동과 action 성공 확인. 0.25m 허용오차로 0.22m 조기 성공하여 0.08m/0.17rad로 조정. 두 번째 주행은 무관한 로그인 세션 만료가 잘못 발생시킨 안전정지로 취소되어 backend 회귀 테스트를 추가했으며 반복 정밀도 시험 필요 |
| Gazebo 무이동 상태→개별/전체 정지 | NOT_RUN | rosbag/로그, command 결과 |
| 두 Gazebo 인스턴스 spawn 위치 분리 | NOT_RUN | x/y spawn 인자를 지원하는 별도 world 또는 launch 수정. 현재 기본 위치 중첩 가능 |
| 1시간 지도+영상 RSS/큐/N01~N03 | NOT_RUN | 측정값, 호스트 사양, 시계 동기 상태 |

실물에서 제공되지 않은 follow/control 서비스는 `UNSUPPORTED`로 표시하며 PASS로 대체하지 않는다. Nav2 action server 또는 AMCL/TF가 준비되지 않으면 자동 주행 버튼을 사용하지 않는다. 서버 재시작 뒤 자동 주행 재개가 관찰되면 즉시 FAIL로 기록하고 임무를 재개하지 않은 상태에서 원인을 수정한다. 시험 중 로봇을 들어 옮길 때는 정지 확인 후 `localization-reset`을 사용하며, 정적 map 파일을 초기화하지 않는다.

rosbridge는 systemd API 서비스와 별도 lifecycle이다. ROS supervisor가 종료·재시작을 관리하며, API 서비스만 재시작해도 rosbridge가 자동으로 생긴다고 가정하지 않는다.

2026-09-14 두 로봇 동시 연결 smoke에서는 robot_1(`192.168.0.8`, domain 12)과 robot_2(`192.168.0.18`, domain 13)가 동시에 `ONLINE`이고 pose가 `FRESH`로 유지됐으며 두 sensor-layer API에서 scan 표본을 수신했다. 초기 API 표본에서는 양쪽 battery도 `FRESH`였지만 30초 표본 중 robot_2 battery가 `STALE`로 전환되어 갱신 안정성은 미통과다. robot_2 카메라는 `OK` 및 JPEG 11,679 bytes를 반환했고 stop latch는 true로 유지됐다. robot_1은 카메라/control workspace와 로봇 내부 rosbridge가 없어 camera `STALE`, mode `UNKNOWN`, capability 없음이 예상대로 표시됐다. Nav2를 비활성화한 무이동 연결 smoke이므로 양쪽 `MAP_TF_UNVERIFIED`는 미해결 gate로 남긴다. 같은 시점의 ICMP 지연은 robot_1 평균 350ms, robot_2 평균 543ms·최대 1.03초로 원격 주행 안정성 기준에는 부적합했다.
