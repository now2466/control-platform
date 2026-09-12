# T12 ROS 2 / rosbridge integration report

## 구현된 관제 연결 계약

`backend/pinky_control_center/resources/config/robots.ros.yaml`은 `robot_1=ROS_DOMAIN_ID 12`, `robot_2=ROS_DOMAIN_ID 13`을 검증하고, 두 개의 서로 다른 rosbridge URL을 요구한다. domain ID는 API와 UI에 노출하거나 변경하는 기능이 없다. backend만 rosbridge에 연결한다.

`RosbridgeAdapter`는 robot별 websocket, 재연결(1/2/4/8초), odom/battery/control-status/path/compressed-camera 구독 및 JPEG cache를 구현했다. configured `fragment_size`로 전송된 rosbridge fragment는 최대 16 active ID·64개/ID·4 MiB/ID·5초로 제한해 재조립하며, 초과·불일치 fragment는 버린다. 연결이 끊기면 해당 robot의 JPEG cache와 pose/battery/camera timestamp, mode/stop latch/capability/path 같은 live control state를 폐기한다. cached JPEG는 camera가 2초 뒤 STALE이 되면 더 이상 반환하지 않는다. ROS Path는 최대 200 point로 latest state snapshot과 path layer event에 반영한다. `Odometry`와 battery timestamp는 분리해 battery 수신이 stale pose를 fresh로 만들지 않는다. `Odometry`는 `map` 좌표로 간주하지 않는다. map-to-odom TF가 실제로 확인될 때까지 `tf_valid=false`, `MAP_TF_UNVERIFIED`로 표시한다.

Optional secure bridge mapping is available only for `wss://` URLs. `security.verify_tls` defaults to true; CA bundle path, client certificate/key paths, and bearer token are referenced by `ca_cert_env`, `client_cert_env`/`client_key_env`, and `authorization_token_env`. YAML stores only environment variable names, never secret values or certificate contents. Missing configured values fail the individual reconnect without logging the value.

## 저장소 조사 결과

실물 robot_2에서 확인한 계약은 `cmd_vel` (`Twist`), `odom` (`Odometry`), `battery/percent`·`battery/voltage` (`Float32`), `scan` (`LaserScan`), `tf`/`tf_static`, 그리고 `rosy_control/camera_detect_node`가 발행하는 raw `/camera/front` (`sensor_msgs/msg/Image`)다. 관제용 카메라는 로봇 세션 런처가 `/camera/front`를 `/camera/image_raw/compressed` (`sensor_msgs/msg/CompressedImage`)로 변환한 뒤 rosbridge가 전달한다. 이 로봇의 Python libcamera 0.3.2와 `/usr/local` IPA는 ROS Jazzy libpisp 1.5.0과 ABI가 다르므로, 세션 런처는 카메라 프로세스에 호환되는 `/usr/local` libpisp 1.0.7을 우선 적용한다. 기존 frame string과 Nav2 설정은 namespace/frame prefix가 실제 2대 환경에서 올바르게 적용되는지 검증되지 않았다.

현재 확인되지 않았거나 제공되지 않은 항목은 다음과 같다.

- robot_1의 실제 endpoint와 robot_2의 TLS/credentials, 그리고 두 로봇의 장기 실행 서비스 환경
- `map -> robot_N/odom -> robot_N/base_footprint` TF tree와 QoS
- domain 13에서 실행되는 camera publisher와 raw-to-CompressedImage bridge
- `pinky_control_interfaces`의 control/follow status, command, heartbeat와 단일 `cmd_vel` mediator
- NavigateToPose action feedback/result, initial pose, costmap의 실제 mapping

따라서 기본 ROS 설정은 새 control/follow endpoint를 이름만 보존하고 `control_available=false`, `follow_available=false`로 둔다. 명령은 `UNSUPPORTED`이며 adapter는 `/cmd_vel`에 직접 쓰지 않는다. scan/costmap은 연결이 없으면 `STALE`, 연결됐지만 mapping/구독이 없으면 `UNSUPPORTED`로 API에 명시한다. 실제 endpoint와 계약이 제공된 뒤에만 해당 플래그를 활성화하고 무이동 상태에서 상태·영상·stop acknowledgement부터 현장 검증해야 한다.

## 실행하지 않은 현장 검증

robot_2 현장 시험에서는 호환 라이브러리 우선 적용 후 domain 13의 카메라가 `320x240 @ 8Hz`로 초기화되는 것을 확인했다. `/camera/front` publisher와 raw-to-compressed republisher, 압축 토픽의 rosbridge 구독은 세션 런처 통합 시험에서 확인한다. 단, 다중 publisher가 남아 있으면 카메라 장치 충돌이 발생하므로 `deployment/scripts/start-pinky-robot2-session.sh`가 중복 camera/republisher/rosbridge를 거부하고, 실패 시 자식 프로세스까지 정리하도록 했다. 실제 영상이 관제 화면에 도착하는지와 stop/watchdog, action 결과 및 이동 시험은 별도 현장 gate에서 확인해야 한다. mock/transport contract test 통과는 실물 안전 제어의 증거가 아니다.
