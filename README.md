# Pinky Pro 2대 관제 플랫폼

작성일: 2026-09-10 · 버전: 1.0 · 상태: 구현 기준안

마스터 1대와 슬레이브 1대의 추종 운용을 위한 독립 관제 플랫폼 프로젝트다. 현재 T01~T05의 모의 실행 범위를 제공하며, 실물 연동은 후속 작업이다.

## 실행

```bash
cd frontend && npm install && npm run dev
```

프런트엔드는 `http://localhost:5173`에서 실행되며 `/api` 요청을 `http://127.0.0.1:8081`로 프록시한다.

백엔드는 별도 터미널에서 다음처럼 실행한다.

```bash
cd backend && .venv/bin/python -m pinky_control_center.main --mode mock --host 127.0.0.1 --port 8081
```

T02 인증을 처음 실행할 때는 먼저 DB와 관리자 계정을 만든다. backend가 제공하는 실제 CLI는 아래와 같다.

```bash
cd backend
mkdir -p ~/.local/state/control-platform
.venv/bin/python -m pinky_control_center.main --database ~/.local/state/control-platform/control.db \
  --reset-password operator --password '<로컬에서만 입력할 비밀번호>' --role ADMIN
.venv/bin/python -m pinky_control_center.main --mode mock --host 127.0.0.1 --port 8081 \
  --database ~/.local/state/control-platform/control.db
```

운영 DB 기본 경로는 `${XDG_STATE_HOME:-~/.local/state}/control-platform/control.db`이며 `--database`로 변경할 수 있다. `--reset-password`는 계정을 생성하거나 비밀번호를 재설정한다. 비밀번호는 저장소나 로그에 기록하지 않는다. 기본 frontend Origin은 `http://localhost:5173`이며 backend의 `create_app(..., allowed_origin=...)` 계약과 일치해야 한다. 세션은 HttpOnly `cc_session`, CSRF는 읽을 수 있는 `cc_csrf` 쿠키로 전달하고, frontend는 로그인 뒤 인증된 상태 API와 `/ws/state`를 사용한다.

## 단계

| 단계 | 범위 | 상태 |
|---|---|---|
| T01 | 계약·환경·모의 실행·기본 화면 | 완료 |
| T02 | 저장·인증·상태 배포 | 완료 |
| T03 | 지도·로봇 카드 | 완료 |
| T04 | 카메라 그리드 | 완료 |
| T05 | 정지·수동 조작·권한 | 완료 |
| T06 | 편대·단일 목표 임무 | 완료(mock) |
| T07 | 경유점·순찰 | 완료(mock) |
| T08 | 지도 센서 레이어 | 미구현 |
| T09 | 설정·로봇 등록 | 미구현 |
| T10 | 기록·검색 | 미구현 |
| T11 | 재생·운영 문서 | 미구현 |
| T12 | ROS 2·실물 인터페이스 연동 | 미구현 |
| T13 | 인증 강화·배포 | 미구현 |
| T14 | 통합 인수·실물 검증 | 미구현 |

T03 화면은 인증된 지도 metadata/PNG와 상태 snapshot의 위치·궤적·경로를 표시하고 카드와 로봇 선택을 동기화한다. T04 카메라 그리드, T06 편대·단일 목표 임무, T07 경유점·순찰을 mock adapter 기준으로 완료했다. 현재 검증은 frontend 43 tests와 backend 66 tests를 통과했으며 실제 ROS 연동은 T12 범위다.

새 기능은 테스트를 먼저 작성해 RED를 확인하고 최소 구현 후 GREEN, 정리 단계까지 진행한다. 단계별 증거는 `docs/tdd/`에 기록하며 설정·수집 실패와 실제 동작 assertion 실패를 구분한다.

T02 범위는 저장·인증·상태 배포다. 로그인 후 세션, CSRF, 인증 상태 API와 상태 WebSocket 재연결을 확인할 수 있다. 실물 정지 래치, watchdog, 수동 조작은 T05 이후 범위이며 아직 구현하지 않는다.

T05 frontend 검증은 frontend Vitest 27개와 backend mock/runtime tests 38개를 통과했다. 정지·watchdog의 동작은 mock/runtime 검증 결과이며 실제 로봇 safety wiring과 ROS watchdog 시험은 T12에서 수행한다.

실물 연결은 로봇별 rosbridge websocket을 사용한다. 배포 고정값은 `robot_1=ROS_DOMAIN_ID 12`, `robot_2=ROS_DOMAIN_ID 13`이며 관제 UI/API에서 domain ID를 변경하지 않는다. backend의 RobotAdapter가 두 연결을 관리하고 bridge URL·인증/TLS·토픽 매핑만 설정으로 관리한다. 브라우저는 rosbridge에 직접 연결하지 않으며 단절 시 reconnect와 stale 상태를 표시한다. 카메라는 rosbridge의 compressed image JSON/base64를 기본으로 하며 quality·throttle·fragment를 조정한다.

## 읽는 순서

1. [요구사항 정의서](docs/01-requirements.md): 범위, 우선순위, 인수 기준, 담당 경계.
2. [기능·인터페이스 명세서](docs/02-functional-spec.md): 화면, 상태 전이, API, ROS 계약, 저장 구조.
3. [구현 계획](docs/03-implementation-plan.md): 파일 구조, 작업 순서, 검증, 실물 연동 게이트.
4. [계약 보완](docs/04-contract-clarifications.md): API와 상태 계약의 보완 규칙.

P0/P1/P2는 개발 순서이다. P2도 최종 납품 범위에 포함한다. 모의 데이터 검증 완료와 실물 로봇 검증 완료는 별도로 보고한다.

## 구현 시 사용할 지시문

> 이 저장소의 docs/ 문서 4개를 읽고 03-implementation-plan.md의 T01부터 순서대로 구현하라. 코드와 문서에 차이가 있으면 확인된 실제 인터페이스를 어댑터 설정에 반영하고 변경 이유를 기록하라. 먼저 mock 모드에서 통합 테스트를 통과시키고 ROS 연동을 수행하라. 각 작업의 인수 기준과 요구사항 추적표를 확인하라. 실제 로봇의 주행 시험은 현장 담당자가 준비한 시험 환경에서 수행하고, 수행하지 못한 실물 검증을 완료로 표시하지 말라. 추종 알고리즘은 로봇 담당 영역이며, 관제에는 계약을 구현한 모의 어댑터와 실제 연동 어댑터를 제공하라.

## 확정한 설계와 외부 의존성

- 관제 PC 1대, 로봇 2대, 로컬 네트워크, 한국어 웹 UI를 기본으로 한다.
- 불변 ID는 `robot_1`, `robot_2`, 역할은 각각 `MASTER`, `SLAVE`이다. 역할 변경은 둘 다 정지한 상태에서만 허용한다.
- React + TypeScript 화면, FastAPI 서버, 로봇별 rosbridge websocket adapter, SQLite 기록, JPEG 프레임 스트림을 구현 기준으로 선택한다. 이는 새 플랫폼의 설계 결정이며 기존 프로젝트에 설치되어 있다는 뜻은 아니다.
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
