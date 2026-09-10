# Pinky Pro 2대 관제 플랫폼 설계 문서

작성일: 2026-09-10 · 버전: 1.0 · 상태: 구현 기준안

이 문서는 마스터 1대와 슬레이브 1대의 추종 운용을 위한 관제 플랫폼을 구현하기 위한 기준이다. 지도 아래에는 각 로봇의 실시간 카메라 영상을 2열 그리드로 표시한다. 요구사항에는 앞서 논의한 지도, 상태, 편대, 임무, 정지, 수동 조작, 알림, 센서, 기록·재생, 설정을 모두 포함한다.

## 읽는 순서

1. [요구사항 정의서](01-requirements.md): 범위, 우선순위, 인수 기준, 담당 경계.
2. [기능·인터페이스 명세서](02-functional-spec.md): 화면, 상태 전이, API, ROS 계약, 저장 구조.
3. [구현 계획](03-implementation-plan.md): 파일 구조, 작업 순서, 검증, 실물 연동 게이트.

P0/P1/P2는 개발 순서이다. P2도 최종 납품 범위에 포함한다. 모의 데이터 검증 완료와 실물 로봇 검증 완료는 별도로 보고한다.

## 구현 시 사용할 지시문

> docs/control-platform의 문서 4개를 읽고 03-implementation-plan.md의 T01부터 순서대로 구현하라. 코드와 문서에 차이가 있으면 확인된 실제 인터페이스를 어댑터 설정에 반영하고 변경 이유를 기록하라. 먼저 mock 모드에서 통합 테스트를 통과시키고 ROS 연동을 수행하라. 각 작업의 인수 기준과 요구사항 추적표를 확인하라. 실제 로봇의 주행 시험은 현장 담당자가 준비한 시험 환경에서 수행하고, 수행하지 못한 실물 검증을 완료로 표시하지 말라. 추종 알고리즘은 로봇 담당 영역이며, 관제에는 계약을 구현한 모의 어댑터와 실제 연동 어댑터를 제공하라.

## 확정한 설계와 외부 의존성

- 관제 PC 1대, 로봇 2대, 로컬 네트워크, 한국어 웹 UI를 기본으로 한다.
- 불변 ID는 `robot_1`, `robot_2`, 역할은 각각 `MASTER`, `SLAVE`이다. 역할 변경은 둘 다 정지한 상태에서만 허용한다.
- React + TypeScript 화면, FastAPI 서버, rclpy 연동, SQLite 기록, JPEG 프레임 스트림을 구현 기준으로 선택한다. 이는 새 플랫폼의 설계 결정이며 기존 프로젝트에 설치되어 있다는 뜻은 아니다.
- 실물 로봇의 토픽명·카메라 타입·TF·추종 제어 서비스는 현재 실행 환경에서 확인되지 않았다. 명세의 ROS 이름은 목표 계약이며 설정으로 매핑한다.
- 실물 안전 제어를 맡는 로봇 측 정지 래치·명령 watchdog·속도 중재기는 로봇 담당과 공동 연동해야 한다. 해당 기능 없이 웹 정지 버튼만으로 실물 검증을 통과시킬 수 없다.
- 시간·거리·속도 기준은 초기 시험값이다. 장비 성능을 확인한 수치가 아니며 하드웨어 허용 범위와 현장 시험으로 확정한다.

## 확인한 기존 코드

| 경로 (저장소 기준) | 확인 사실 | 설계 반영 |
|---|---|---|
| `README.md` | Ubuntu 24.04, ROS 2 Jazzy 안내 | 관제 ROS 실행 기준 |
| `pinky_navigation/scripts/nav2_web_server.py` | Flask, 맵·TF·경로·costmap, NavigateToPose, 초기 위치, 취소, SLAM API | 좌표 처리와 ROS 연결 참고. 단일 로봇 서버를 그대로 복제하지 않고 로봇별 어댑터 구성 |
| `pinky_navigation/scripts/index.html` | 기존 웹 관제 화면 | 지도 상호작용 참고 |
| `pinky_bringup/pinky_bringup/battery_publisher.py` | Float32 `battery/percent`, `battery/voltage`, 5초 주기 | 배터리 신선도는 위치와 다른 기준 사용 |
| `pinky_bringup/pinky_bringup/bringup.py` | `cmd_vel`, `odom`, 고정 `odom`/`base_footprint` 프레임 | namespace만 붙여서는 TF 충돌이 해결되지 않음 |
| `pinky_gz_sim/launch/launch_sim.launch.xml` | ros_gz_image, `/camera/image_raw` 및 `/camera` 브리지 | 시뮬레이터 영상 연동 참고. 실물 토픽은 별도 검증 |
| `pinky_navigation/launch/navigation_launch.xml` | `cmd_vel_nav`와 최종 `cmd_vel` remap | 최종 구동 출력의 단일 중재 지점 필요 |

기존 파일은 조사만 했다. 이 문서 작성 과정에서 주행 명령 발행, 코드 변경, 실물 성능 검증은 수행하지 않았다.

## 기술 근거

- [ROS 2 Jazzy QoS 공식 문서](https://docs.ros.org/en/jazzy/Concepts/Intermediate/About-Quality-of-Service-Settings.html): 발행자와 구독자의 QoS 호환성을 연동 검증 대상으로 둔다.
- [FastAPI WebSocket 공식 문서](https://fastapi.tiangolo.com/advanced/websockets/): 상태·이벤트 실시간 채널을 구현할 때 참고한다.

그 밖의 수치와 운영 정책은 본 프로젝트의 제안된 요구사항이며 외부 표준의 보증 값이 아니다.
