# T12 ROS 2 / rosbridge integration report

## 구현된 관제 연결 계약

`backend/pinky_control_center/resources/config/robots.ros.yaml`은 `robot_1=ROS_DOMAIN_ID 12`, `robot_2=ROS_DOMAIN_ID 13`을 검증하고, 두 개의 서로 다른 rosbridge URL을 요구한다. domain ID는 API와 UI에 노출하거나 변경하는 기능이 없다. backend만 rosbridge에 연결한다.

`RosbridgeAdapter`는 robot별 websocket, 재연결(1/2/4/8초), odom/battery/control-status/path/compressed-camera 구독 및 JPEG cache를 구현했다. configured `fragment_size`로 전송된 rosbridge fragment는 최대 64개·4 MiB·5초로 제한해 재조립하며, 초과·불일치 fragment는 버린다. 연결이 끊기면 해당 robot의 JPEG cache도 폐기한다. `Odometry`와 battery timestamp는 분리해 battery 수신이 stale pose를 fresh로 만들지 않는다. `Odometry`는 `map` 좌표로 간주하지 않는다. map-to-odom TF가 실제로 확인될 때까지 `tf_valid=false`, `MAP_TF_UNVERIFIED`로 표시한다.

## 저장소 조사 결과

`/home/yoon/pinky/src/pinky_pro`에서 확인한 현재 bringup 계약은 `cmd_vel` (`Twist`), `odom` (`Odometry`, 30 Hz), `battery/percent`·`battery/voltage` (`Float32`, 5초), `scan` (`LaserScan`), raw `camera/image_raw`, 고정 `odom -> base_footprint` TF다. 기존 frame string과 Nav2 설정은 namespace/frame prefix가 실제 2대 환경에서 올바르게 적용되는지 검증되지 않았다.

현재 확인되지 않았거나 제공되지 않은 항목은 다음과 같다.

- robot별 rosbridge URL, TLS/credentials 및 실행 프로세스의 `ROS_DOMAIN_ID` 값
- `map -> robot_N/odom -> robot_N/base_footprint` TF tree와 QoS
- compressed image topic 또는 raw-to-CompressedImage bridge
- `pinky_control_interfaces`의 control/follow status, command, heartbeat와 단일 `cmd_vel` mediator
- NavigateToPose action feedback/result, initial pose, costmap의 실제 mapping

따라서 기본 ROS 설정은 새 control/follow endpoint를 이름만 보존하고 `control_available=false`, `follow_available=false`로 둔다. 명령은 `UNSUPPORTED`이며 adapter는 `/cmd_vel`에 직접 쓰지 않는다. scan/costmap은 연결이 없으면 `STALE`, 연결됐지만 mapping/구독이 없으면 `UNSUPPORTED`로 API에 명시한다. 실제 endpoint와 계약이 제공된 뒤에만 해당 플래그를 활성화하고 무이동 상태에서 상태·영상·stop acknowledgement부터 현장 검증해야 한다.

## 실행하지 않은 현장 검증

이 환경에는 두 실제 rosbridge endpoint와 ROS graph가 없으므로 연결, TLS, QoS, TF, camera, stop/watchdog, action 결과와 이동 시험은 실행하지 않았다. mock/transport contract test 통과는 실물 안전 제어의 증거가 아니다.
