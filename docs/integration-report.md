# T12 ROS 2 / rosbridge integration report

## 구현된 관제 연결 계약

`backend/pinky_control_center/resources/config/robots.ros.yaml`은 `robot_1=ROS_DOMAIN_ID 12`, `robot_2=ROS_DOMAIN_ID 13`을 검증하고, 두 개의 서로 다른 rosbridge URL을 요구한다. domain ID는 API와 UI에 노출하거나 변경하는 기능이 없다. backend만 rosbridge에 연결한다.

`RosbridgeAdapter`는 robot별 websocket, 재연결(1/2/4/8초), odom/battery/control-status/path 구독을 구현했다. 카메라가 활성인 프로필만 compressed-camera를 추가 구독하고 JPEG cache를 사용한다. configured `fragment_size`로 전송된 rosbridge fragment는 최대 16 active ID·64개/ID·4 MiB/ID·5초로 제한해 재조립하며, 초과·불일치 fragment는 버린다. 연결이 끊기면 해당 robot의 JPEG cache와 pose/battery/camera timestamp, mode/stop latch/capability/path 같은 live control state를 폐기한다. cached JPEG는 camera가 2초 뒤 STALE이 되면 더 이상 반환하지 않는다. ROS Path는 최대 200 point로 latest state snapshot과 path layer event에 반영한다. `Odometry`와 battery timestamp는 분리해 battery 수신이 stale pose를 fresh로 만들지 않는다. `Odometry`는 `map` 좌표로 간주하지 않는다. map-to-odom TF가 실제로 확인될 때까지 `tf_valid=false`, `MAP_TF_UNVERIFIED`로 표시한다.

Optional secure bridge mapping is available only for `wss://` URLs. `security.verify_tls` defaults to true; CA bundle path, client certificate/key paths, and bearer token are referenced by `ca_cert_env`, `client_cert_env`/`client_key_env`, and `authorization_token_env`. YAML stores only environment variable names, never secret values or certificate contents. Missing configured values fail the individual reconnect without logging the value.

## 저장소 조사 결과

실물 robot_2에서 확인한 계약은 `cmd_vel` (`Twist`), `odom` (`Odometry`), `battery/percent`·`battery/voltage` (`Float32`), `scan` (`LaserScan`), `tf`/`tf_static`, 그리고 `rosy_control/camera_detect_node`가 발행하는 raw `/camera/front` (`sensor_msgs/msg/Image`)다. 관제용 카메라는 로봇 세션 런처가 `/camera/front`를 `/camera/image_raw/compressed` (`sensor_msgs/msg/CompressedImage`)로 변환한 뒤 rosbridge가 전달한다. 이 로봇의 Python libcamera 0.3.2와 `/usr/local` IPA는 ROS Jazzy libpisp 1.5.0과 ABI가 다르므로, 세션 런처는 카메라 프로세스에 호환되는 `/usr/local` libpisp 1.0.7을 우선 적용한다. 기존 frame string과 Nav2 설정은 namespace/frame prefix가 실제 2대 환경에서 올바르게 적용되는지 검증되지 않았다.

2026-09-14 YYM Wi-Fi에서 `robot_1=172.20.10.9`, `robot_2=172.20.10.8`로 식별했다. 두 장비는 복제 이미지로 hostname과 `/etc/machine-id`가 같지만 WLAN MAC은 서로 다르다. robot_1에는 아직 rosbridge와 control workspace가 없으므로 연결 시험은 PC의 domain 12 rosbridge를 사용하고, robot_2는 로봇 내부 domain 13 rosbridge를 사용한다.

같은 날 동시 연결 smoke에서 두 로봇의 pose·scan과 robot_2 압축 영상은 계속 수신됐지만, PC에서 측정한 ICMP 왕복 지연은 robot_1 평균 350ms, robot_2 평균 543ms·최대 1.03초였다. robot_2 배터리는 초기 수신 뒤 freshness가 간헐적으로 `STALE`이 됐다. 이 상태는 연결 확인에는 충분하지만 원격 수동·자동 주행의 안정성 gate는 통과하지 못한 것으로 기록한다.

현재 확인되지 않았거나 제공되지 않은 항목은 다음과 같다.

- robot_1의 로봇 내부 rosbridge/control/camera 설치와 robot_2의 TLS/credentials, 그리고 두 로봇의 장기 실행 서비스 환경
- `map -> robot_N/odom -> robot_N/base_footprint` TF tree와 QoS
- domain 13 camera publisher와 raw-to-CompressedImage bridge는 세션 smoke에서 확인했으며, 장기 실행·실제 FPS 측정은 별도 gate다.
- `pinky_control_interfaces`의 control status/command와 `pinky_control_watchdog` 단일 `cmd_vel` mediator는 저장소와 robot_2용 session script에 추가했다. follow status/command와 heartbeat의 backend 소비는 아직 미완료다.
- `ros/pinky_control_navigation`에 `map_260905.world`에서 생성한 정적 `map_260905.pgm/.yaml`, AMCL·map server·Nav2 launch와 `/control/nav_velocity` remap을 추가했다. robot_2 workspace의 세 패키지 build는 통과했으며, 실제 action server/lifecycle 활성 상태는 별도 gate다.
- NavigateToPose action feedback/result의 최종 상태를 backend 명령 이력으로 직접 수집하는 mapping, AMCL initial pose가 실제 map→odom을 만드는지, costmap과 footprint의 실제 mapping

기본 번들 ROS 설정은 새 control/follow endpoint를 이름만 보존하고 `control_available=false`, `follow_available=false`로 둔다. robot_2 현장 설정(`deployment/robots.ros.local.yaml`)은 watchdog service 계약을 포함해 `control_available=true`로 둔다. adapter는 `/cmd_vel`에 직접 쓰지 않고 `/control/manual_velocity`만 발행한다. scan/costmap은 연결이 없으면 `STALE`, 연결됐지만 mapping/구독이 없으면 `UNSUPPORTED`로 API에 명시한다. control status가 올라오고 stop/reset/mode service 응답 및 `navigate` capability가 확인된 뒤에만 저속 주행 시험을 진행한다.

## T15 지도 주행·AMCL 재현지화 구현 상태

관제의 `/robots/{id}/navigate`는 start pose와 goal이 활성 정적 지도에서 자유 셀인지, 선택 로봇이 ONLINE/FRESH·정지·IDLE·편대 해제인지, lease와 `navigate` capability가 유효한지 확인한다. 수락된 실행은 `/initialpose` → `AUTO` → watchdog의 `NavigateToPose` action 순서다. `/robots/{id}/localization-reset`은 로봇을 들어 옮긴 뒤 `/initialpose`만 발행하며, 정적 지도나 SLAM 상태를 초기화하지 않는다.

robot_2 session script는 `START_NAV2=1`일 때 watchdog 뒤 SLLidar의 `/start_motor`를 호출하고 `pinky_control_navigation`을 시작한 뒤 `/navigate_to_pose` action server가 보일 때까지 기다린다. navigation lifecycle gate는 `map→base_footprint` TF가 확인된 뒤에만 lifecycle manager startup을 호출하고 실패 시 재시도한다. Nav2 controller/recovery는 `/control/nav_velocity`로 remap되고 최종 `/cmd_vel`은 watchdog 하나만 발행한다. `stop`, `reset_stop`, `cancel_navigation`은 활성 goal을 취소하며 자동 재개하지 않는다.

재부팅 후 수동 단계 누락을 줄이기 위해 `deployment/scripts/start-pinky-robot2-all.sh`를 추가했다. 이 wrapper는 부팅 시 domain 0으로 시작되는 기존 rosy bringup/control user service를 중지하고, domain 13 hardware bringup의 `/odom`·`/scan`을 확인한 뒤 기존 session script를 시작한다. `/navigate_to_pose`까지 확인된 뒤에만 all-in-one READY를 표시하며, 종료 시 session을 먼저 내리고 bringup을 종료한다. AMCL 초기 위치는 의도적으로 자동 복구하지 않으며 매 재부팅 후 현장 위치·방향을 웹에서 다시 지정해야 한다.

mock API/UI와 launch/package syntax, robot_2의 세 패키지 build는 검증했다. 실제 로봇에서는 map server/AMCL/Nav2 lifecycle active, `map→odom→base_footprint` TF, action acceptance/result와 1차 저속 이동까지 확인했다. 남은 gate는 라이다 costmap 장애물 반영, 조정된 허용오차의 반복 도착 정밀도, 정지 및 수동 재배치 후 재현지화다.

robot_2 1차 현장 주행에서 `/scan` 약 10Hz, AMCL·Nav2 lifecycle active, `map→odom→base_footprint` TF, `/navigate_to_pose` action acceptance와 실제 이동을 확인했다. 마지막 action은 `SUCCEEDED`였지만 목표 `(1.20, -0.04)` 대비 정지 pose가 약 `(1.20, 0.18)`로 0.22m 일찍 멈췄다. 이는 `general_goal_checker.xy_goal_tolerance=0.25` 안에 들어온 정상 판정이므로 현장 클릭 주행 설정을 `xy_goal_tolerance=0.08`, `yaw_goal_tolerance=0.17`로 강화했다. 조정값의 반복 도착 정밀도와 장애물 회피는 아직 현장 gate다.

두 번째 현장 주행은 목표 `(1.21, -0.18)`로 이동 중 pose 약 `(1.20, -0.05)`에서 action status 5 `CANCELED`로 종료됐다. 같은 시각 backend history에는 사용자 명령 없이 pair-wide `SAFETY_STOP`이 기록됐다. 원인은 `expire_security()`가 제어 lease를 소유하지 않은 과거 로그인 세션 만료까지 제어권 상실로 반환한 것이며, 이제 로그인 세션 만료는 해당 세션 소유의 활성 lease를 제거한 경우에만 보호 정지를 발생시킨다.

허용오차 변경 배포 시 `/home/pinky/dev_ws/wj`의 전체 `rosdep install --from-paths src -y --ignore-src`는 기존 `lcd_control`·`pinky_web`의 사내 패키지 키와 두 제어 패키지의 `ament_python` rosdep 키를 해석하지 못해 실패했다. 새 의존성이 없는 YAML 변경이므로 `colcon build --packages-select pinky_control_navigation`으로 대상 패키지 빌드를 완료했으며, rosdep 선언 정리는 별도 유지보수 항목이다.

## 실행하지 않은 현장 검증

2026-09-14 YYM 현장 운용에서는 네트워크 대역폭 확보를 위해 두 로봇의 카메라 발행과 관제 구독을 모두 비활성화했다. domain 13 세션 런처는 더 이상 `camera_detect_node`나 raw-to-compressed republisher를 시작하지 않으며, `deployment/robots.ros.local.yaml`의 `camera.enabled=false`가 rosbridge 이미지 구독을 막는다. 아래 카메라 검증 기록은 기능이 활성화됐던 이전 시험 이력이다.

robot_2 현장 시험에서는 호환 라이브러리 우선 적용 후 domain 13의 카메라가 `320x240 @ 8Hz`로 초기화되는 것을 확인했다. `/camera/front` publisher와 raw-to-compressed republisher, 압축 토픽의 rosbridge 구독은 세션 런처 통합 시험에서 확인했다. 단, 다중 publisher가 남아 있으면 카메라 장치 충돌이 발생하므로 `deployment/scripts/start-pinky-robot2-session.sh`가 중복 camera/republisher/rosbridge/watchdog를 거부하고, 실패 시 자식 프로세스까지 정리하도록 했다. 실제 영상, stop/watchdog acknowledgement, Nav2/AMCL, action 성공과 1차 이동은 확인했다. 반복 도착 정밀도·장애물 회피·수동 재배치 후 재현지화는 별도 현장 gate이며, mock/transport contract test 통과만으로 실물 안전 제어를 증명하지 않는다.
