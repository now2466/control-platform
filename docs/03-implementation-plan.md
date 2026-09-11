# Pinky Pro 관제 플랫폼 구현 계획

목표: 지도·2개 카메라 그리드·편대 임무·정지·알림·기록을 갖춘 웹 관제 플랫폼을 모의 실행에서 실물 2대 연동까지 구현한다.

기준 문서: [요구사항](01-requirements.md), [기능 명세](02-functional-spec.md), [문서 안내](../README.md). 이 저장소는 독립 프로젝트이며 문서 작성 시점에는 아래 작업을 실행하지 않았다.

## 1. 구현 원칙과 기본 선택

- Python 3.12, Ubuntu 24.04, ROS 2 Jazzy를 ROS 실행 기준으로 한다.
- React/TypeScript/Vite + FastAPI + SQLite를 사용한다. 실물 ROS는 로봇별 rosbridge websocket client(adapter)가 담당하며 실제 의존 버전은 T01에서 설치·빌드 확인 후 lock 파일에 고정한다.
- 모든 제어는 서버에서 대상 ID, 권한, lease, 상태, 값 범위를 검증한다.
- ROS 이름은 설정으로 매핑한다. mock은 ROS 없이 실행하며 ros 모드 장애를 mock으로 숨기지 않는다.
- UI에 작업 중/완료/실패를 명시한다. 실제 수신 확인 없는 성공 표시는 금지한다.
- T01~T14 전체가 최종 범위다. MVP 이후 작업을 누락하지 않는다.
- 테스트는 위험한 상태 전이·좌표·중복 명령·끊김·기록 경계를 중심으로 작성한다.
- 기존 웹 서버는 참고만 하고 새 패키지에서 구현한다. 하드웨어 드라이버 변경은 T12에서 실제 연결 조사 후 필요한 범위만 수행한다.

## 2. 예정 파일 구조

아래 경로는 이 독립 저장소 루트 기준이며 새로 만들 파일이다.

```text
ros/pinky_control_interfaces/ (T12 예정)
  CMakeLists.txt, package.xml
  msg/ControlStatus.msg, msg/FollowStatus.msg
  srv/ControlCommand.srv, srv/FollowCommand.srv
backend/
  package.xml, setup.py, setup.cfg, pyproject.toml, requirements.lock
  resource/pinky_control_center
  config/robots.mock.yaml, config/robots.ros.yaml, config/defaults.yaml
  launch/control_center.launch.py
  pinky_control_center/
    __init__.py, main.py, config.py, models.py
    adapters/base.py, adapters/mock.py, adapters/ros.py
    state_store.py, command_service.py, formation_service.py
    mission_service.py, safety_service.py, alert_service.py
    camera_service.py, recording_service.py, replay_service.py
    settings_service.py, map_service.py, accessory_service.py
    auth.py, storage.py, migrations/001_initial.sql
    api/session.py, api/state.py, api/control.py, api/missions.py
    api/maps.py, api/cameras.py, api/history.py, api/settings.py
  tests/test_contracts.py, test_state.py, test_commands.py
  tests/test_safety.py, test_formation.py, test_missions.py
  tests/test_cameras.py, test_alerts.py, test_history.py
  tests/test_settings.py, test_ros_mapping.py, test_auth.py
frontend/
  package.json, package-lock.json, tsconfig.json, vite.config.ts
  index.html, src/main.tsx, src/App.tsx, src/styles.css
  src/api/client.ts, src/api/types.ts, src/store.ts
  src/features/map/MapPanel.tsx, transforms.ts, transforms.test.ts
  src/features/robots/RobotCards.tsx
  src/features/cameras/CameraGrid.tsx, CameraTile.tsx, frameDecoder.ts
  src/features/formation/FormationPanel.tsx
  src/features/control/StopBar.tsx, TeleopPanel.tsx
  src/features/missions/MissionPanel.tsx
  src/features/alerts/AlertList.tsx
  src/features/history/HistoryPage.tsx, ReplayPage.tsx
  src/features/settings/SettingsPage.tsx
  tests/dashboard.spec.ts, safety.spec.ts, missions.spec.ts, replay.spec.ts
deployment/
  control-center.service, reverse-proxy.conf, env.example
docs/
  integration-report.md, acceptance-report.md, runbook.md
```

各 Python 디렉터리의 `__init__.py`를 포함해 패키징한다. JS 테스트는 Vitest(단위), Playwright(화면), Python은 pytest. ROS 통합은 rosbridge adapter contract test와 실제 두 domain endpoint/TF 그래프 확인을 병행한다.

## 3. 공통 어댑터 경계

`models.py`에서 명세의 RobotState/FormationState/Command/Mission/Alert와 아래 모델을 Pydantic으로 정의하고, OpenAPI로 프런트엔드 타입을 생성한다. 프런트엔드에서 타입을 별도 추측해 복제하지 않는다.

```python
# 인터페이스 계약. DTO 필드는 기능 명세의 JSON/ROS 계약과 같다.
class RobotAdapter(Protocol):
    async def connect(self) -> None: ...
    async def close(self) -> None: ...
    async def execute(self, command: CommandRequest) -> CommandAcceptance: ...
    def events(self) -> AsyncIterator[AdapterEvent]: ...
    def frames(self, robot_id: str) -> AsyncIterator[CameraFrame]: ...
```

`CommandRequest`: command_id, robot_id, operation, parameters(dict). `CommandAcceptance`: accepted(bool), reason_code(nullable string). `AdapterEvent`: kind(robot_state/formation/command/map/path/scan/costmap), robot_id(nullable), received_at, payload(dict). `CameraFrame`: robot_id, frame_id, captured_at(nullable), received_at, width, height, jpeg(bytes). 구체 payload는 kind별 모델로 검증한다. execute는 수락만 반환하고 완료는 events로 전달한다.

## 4. 작업 목록

### T01 — 계약·환경·모의 실행 기반 (R01, R19)

파일: 패키지 선언/lock/config, models.py, adapters/base.py, adapters/mock.py, main.py, tests/test_contracts.py, 프런트엔드 기본 파일.

- [ ] 의존성 설치 환경과 기존 변경을 확인하고 필요한 버전을 lock한다. 실물 ROS client는 T12의 rosbridge websocket adapter로 연결하며 browser direct rosbridge는 금지한다.
- [ ] 기능 명세의 모델·enum·에러 스키마를 구현하고 ID 중복/NaN/범위 밖 입력 거부 테스트를 작성한다.
- [ ] robot_1/robot_2, 공통 모의 지도, 서로 다른 로봇명·시각이 그려진 JPEG 영상을 생성하는 mock adapter를 만든다.
- [ ] mock profile은 정상, slave_offline, camera_stall, follow_lost, command_rejected를 제공한다. mock 전용 `/api/v1/mock/scenario`로 profile을 선택하고 ros 모드에는 이 경로를 등록하지 않는다.
- [ ] main의 `--mode mock --host 127.0.0.1 --port 8081` 실행 계약을 구현한다.

검증: `python -m pytest backend/tests/test_contracts.py -q`. ROS를 import할 수 없는 환경에서도 mock 기동, 두 robot ID와 구별되는 영상 확인. 이 단계는 모의 기반 완료이며 실물 연결 완료가 아니다.

### T02 — 저장·인증·상태 배포 (R03, R18, N04, N09)

파일: backend/pinky_control_center/storage.py, backend/pinky_control_center/migrations/001_initial.sql, backend/pinky_control_center/auth.py, backend/pinky_control_center/state_store.py, backend/pinky_control_center/api/session.py, backend/pinky_control_center/api/state.py, backend/tests/test_auth.py, backend/tests/test_state.py.

- [x] SQLite migration 및 명령 request_id unique 제약을 생성한다. 비밀번호 초기화 CLI를 제공하고 평문 비밀번호를 DB/로그에 남기지 않는다.
- [x] session·역할·CSRF·Origin 검사, lease 생성/갱신/반납을 구현한다.
- [x] 상태 snapshot과 5Hz WS 배포, field별 freshness, 재접속 snapshot 복구를 구현한다.
- [x] 가짜 시계로 위치 1초·배터리 15초를 각각 넘겨 잘못된 정상 표시가 없는지 확인한다.

검증: `python -m pytest backend/tests/test_auth.py backend/tests/test_state.py -q`. 401/403, 중복 제어권 409, 상태 끊김·복구 통과.

### T03 — 지도·로봇 카드 (R01~R04, N01, N08)

파일: backend/pinky_control_center/api/maps.py, backend/pinky_control_center/map_service.py, frontend/src/MapPanel.tsx, frontend/src/transforms.ts, frontend/src/App.tsx, frontend/src/transforms.test.ts, frontend/src/MapPanel.test.tsx, backend/tests/test_maps.py.

- [x] 지도 metadata/PNG 캐시와 로봇 pose/path를 연결한다.
- [x] 비영점·회전 origin, 줌/팬, canvas y반전의 좌표 왕복 테스트를 작성한다. 임의 점 world→screen→world 오차 1e-6m 이하.
- [x] 두 위치·방향·궤적·목표·경로, 배터리·속도·모드·신선도 카드를 구현한다.
- [x] TF 없는 로봇은 경고 표시, 거리 null 처리. 클릭 선택이 카드와 지도에서 일치하게 한다.

검증: `cd frontend && npm run test` (13 tests), `cd backend && python -m pytest -q` (17 tests; map targeted 3 tests 포함). T04의 영상 그리드와 T06의 목표 명령·편대 제어는 이 단계에 포함하지 않는다.

### T04 — 지도 아래 카메라 그리드 (R05, N02, N07)

파일: camera_service.py, api/cameras.py, CameraGrid.tsx, CameraTile.tsx, frameDecoder.ts, test_cameras.py, dashboard.spec.ts.

- [ ] 명세의 binary WS 프레임 encoder/decoder, 인증, 로봇별 최신 프레임 큐를 구현한다.
- [ ] 지도 바로 아래 2열, 좁은 화면 1열, 로봇명·역할·FPS·신선도·품질·전체화면을 구현한다.
- [ ] camera_stall로 한 영상만 중단하고 2초 경고·5초 가림 및 다른 영상 지속을 검증한다.
- [ ] 언마운트/재연결 때 socket과 Blob URL을 해제하고 시청자 없는 중계 작업을 중단한다.

검증: `python -m pytest backend/tests/test_cameras.py -q` 및 frontend/tests/dashboard.spec.ts. 반복 확대/축소·재연결에서도 프레임 메모리가 쌓이지 않아야 한다.

### T05 — 명령·정지·수동 제어 (R09, R10, R18, N03, N06)

파일: command_service.py, safety_service.py, api/control.py, StopBar.tsx, TeleopPanel.tsx, test_commands.py, test_safety.py, safety.spec.ts.

- [x] idempotency와 202 접수, 수락/완료 상태, timeout·늦은 결과를 구현한다.
- [x] 전체/개별 정지의 로봇별 상태, 정지 래치 해제와 주행 재개의 분리를 구현한다.
- [x] 제어권·수동 모드·10Hz 입력·포커스 상실·브라우저 끊김 처리를 구현한다. mock에서 로봇 watchdog을 재현한다.
- [x] 동일 request_id 2회 전송 시 execute 1회, 슬레이브 무응답 시 전체 정지 성공 미표시, lease 상실 시 양쪽 중단을 테스트한다.

검증: backend tests 38개와 frontend tests 27개. 모의/runtime 정지 성공은 실물 safety wiring·ROS watchdog 구현의 증거가 아니며 T12에서 별도 검증한다.

### T06 — 편대·단일 임무 (R04, R06, R08)

파일: formation_service.py, mission_service.py, api/missions.py, FormationPanel.tsx, MissionPanel.tsx, test_formation.py, test_missions.py, missions.spec.ts.

- [x] 명세 상태 전이를 표 기반으로 구현하고 불가능한 전이를 409로 거부한다.
- [x] pair → 추종 준비 → 마스터 목표 순서를 보장한다. 슬레이브 준비 거절 시 마스터 goal 전송 0회를 검증한다.
- [x] 목표 미리보기·진행·도착, 간격·방위각, 이탈·재합류와 일시정지를 구현한다.
- [x] 마스터만 도착했을 때 임무 성공을 보류하고 슬레이브 최종 정지 확인/10초 제한을 적용한다.

검증: backend 56 tests, frontend 33 tests와 production build. pair/거절/이탈·재합류 실패/일시정지와 단일 목표 임무의 create → validate → start 흐름을 mock adapter와 DOM/API 테스트로 재현한다. 실제 ROS action·TF·정지 연동은 T12에서 검증한다.

### T07 — 경유점·순찰 (R07)

파일: mission_service.py, MissionPanel.tsx, test_missions.py, missions.spec.ts.

- [ ] 1~100개 경유점, 반복 횟수, 편집/저장/정렬과 현재 지점·회차를 구현한다.
- [ ] pause에서 진행 지점 저장, resume에서 해당 지점 재목표화, cancel에서 양쪽 정지 확인을 구현한다.
- [ ] 3지점×2회 경로의 목표 호출 순서와 실패 시 다음 지점 미전송을 검증한다.
- [ ] 서버 재시작 후 PAUSED 복구와 자동 주행 금지를 검증한다.

검증: test_missions.py 및 missions.spec.ts에 순찰·재시작 시나리오를 추가한다.

### T08 — 알림·센서 상세 (R11, R12)

파일: alert_service.py, AlertList.tsx, MapPanel.tsx, test_alerts.py, adapters/mock.py.

- [ ] 명세 임계값·지속 시간·해소 hysteresis·중복 억제·ACK를 구현한다.
- [ ] 선택 로봇 scan/costmap 레이어와 필수 노드·sensor 상태를 표시한다.
- [ ] stale 배터리로 저전력 판단 금지, 카메라 단절은 영상 의존 수동 제어만 차단, 추종/TF 이상은 편대 정지 정책을 검증한다.
- [ ] 활성 경고를 확인 처리해도 원인이 남으면 ACTIVE를 유지한다.

검증: `python -m pytest backend/tests/test_alerts.py -q`, 지도 레이어 선택·로봇 전환 화면 테스트.

### T09 — 설정·지도 관리·식별 장치 (R15~R17)

파일: settings_service.py, map_service.py, accessory_service.py, api/settings.py, SettingsPage.tsx, test_settings.py.

- [ ] 범위·설정 버전 충돌, 양쪽 적용 결과, 실패 시 이전 활성 설정 유지를 구현한다.
- [ ] 정지 중 초기 위치 설정, 지도 선택/저장/리셋을 구현한다. 지도 변경 시 이전 목표/경로·편대 연결은 무효화한다.
- [ ] 기존 SetLed/SetLamp 및 감정 서비스 정의를 읽어 장치별 입력 모델을 만들고 미지원 capabilities를 UI에 반영한다.
- [ ] 이동 중 역할/지도/추종 제한 변경 거부와 모의 부분 적용 실패를 검증한다.

검증: `python -m pytest backend/tests/test_settings.py -q` 및 frontend 설정 화면 입력 경계 테스트.

### T10 — 기록·이력·내보내기 (R13, N10, N11)

파일: storage.py, api/history.py, HistoryPage.tsx, test_history.py.

- [ ] 5Hz telemetry, 명령·결과·이벤트·알림 저장과 인덱스를 구현한다.
- [ ] 로봇/임무/시간 필터와 cursor 페이지, CSV/JSON 다운로드를 구현한다.
- [ ] UTC 저장·KST 표시, CSV 셀 수식 시작 문자 무해화, 24시간 export 제한을 검증한다.
- [ ] 저장 실패는 경고·기록 장애 상태로 노출하고 정지 실행이 DB 실패에 막히지 않게 한다. 정지 감사 이벤트는 복구 후 보충한다.

검증: `python -m pytest backend/tests/test_history.py -q`. 임무 생성부터 취소까지 request_id로 결과를 추적할 수 있어야 한다.

### T11 — 영상 기록·동기 재생 (R14, N10)

파일: recording_service.py, replay_service.py, api/history.py, ReplayPage.tsx, test_history.py, replay.spec.ts.

- [ ] opt-in 녹화 5FPS, 파일/DB 인덱스, 7일/10GB 한도와 2GB 잔여 기준을 구현한다.
- [ ] 공통 received_at 시간축, 프레임 500ms 공백·위치 1초 공백, 재생 배속·탐색을 구현한다.
- [ ] 미녹화·삭제된 구간을 오류 없이 표시하고 파일 유실을 경고한다.
- [ ] 재생 조작에서 실물 명령 API가 호출되지 않는 것을 spy로 검증한다. 별도 LIVE 긴급정지만 명시적 대상으로 허용한다.

검증: test_history.py 및 `npx playwright test tests/replay.spec.ts`. 두 로봇 서로 다른 프레임 시각으로 정렬 정확성을 확인한다.

### T12 — 로봇별 rosbridge·ROS 2 인터페이스 연동 (전체 기능의 실물 기반)

파일: ros/pinky_control_interfaces 전체, backend/pinky_control_center/adapters/ros.py, backend/config/robots.ros.yaml, backend/launch 파일, backend/tests/test_ros_mapping.py, docs/integration-report.md.

- [ ] 로봇별 rosbridge websocket endpoint, 고정 ROS_DOMAIN_ID(`robot_1=12`, `robot_2=13`), topic/service/action 목록과 실제 타입·QoS, TF tree, 카메라, 속도 상한을 읽기 전용 조사한다. 결과를 docs/integration-report.md에 기록한다.
- [ ] T12 예정 `backend/config/robots.ros.yaml`에 bridge endpoint/credentials/TLS/mapping과 고정 domain(`robot_1: 12`, `robot_2: 13`)을 기록하고 RobotAdapter를 두 개 구성해 rosbridge JSON 요청·feedback·결과를 연결한다. rosbridge 프로세스는 각 domain 환경으로 시작하며 관제 UI/API로 domain을 변경하지 않는다. `ros/pinky_control_interfaces`는 로봇 측 계약이 필요할 때만 유지한다.
- [ ] namespaced 토픽과 TF를 각기 검증한다. 기존 고정 odom/base_footprint는 로봇 담당과 수정·설정하고 TF 경로를 실측 확인한다.
- [ ] 로봇 담당이 control/follow 계약, 단일 cmd_vel 중재, stop 래치·watchdog을 구현한 결과를 연결한다. 미제공 기능은 UNSUPPORTED를 유지한다.
- [ ] compressed image 토픽을 rosbridge JSON/base64로 수신하고 quality/throttle/fragment를 설정한다. 단절·재연결·stale 전환과 두 로봇 데이터/제어 대상이 바뀌지 않는 contract test를 실행한다.
- [ ] 무이동 상태에서 상태·영상·정지 응답을 먼저 시험한다. 현장 이동 시험 전에는 실물 속도 제어 enable을 열지 않는다.

검증 (워크스페이스 `/home/yoon/pinky`):

```bash
python -m pytest backend/tests/test_ros_mapping.py -q
python -m pytest backend/tests/test_rosbridge_adapter.py -q
```

실물 전제 미충족 시 mock 완료와 ROS 구현 완료를 구별해 보고하고 integration-report.md에 정확한 누락 계약과 담당을 남긴다.

### T13 — 배포·실행 문서 (N05, N09)

파일: deployment 전체, runbook.md, launch/control_center.launch.py.

- [ ] 동일 출처 정적 UI/API/WS 프록시, TLS·세션 설정, worker 1개 서비스와 env 예제를 작성한다.
- [ ] runbook에 의존성/빌드/계정 생성/mock 실행/ROS 실행/정지/로그 위치/백업/복구 명령을 실제 확인한 값으로 적는다.
- [ ] 자동 시작은 관찰 모드로 제한하고 server restart가 임무 재개를 유발하지 않는지 검사한다.
- [ ] 설정 오류/포트 충돌/ROS 미기동은 명확한 메시지로 실패시키고 기본값으로 다른 로봇에 연결하지 않는다.

검증: 새 환경에서 runbook만 따라 mock 실행, 실제 ROS 환경에서 ros 기동. 인증 없는 REST/영상/WS 접근 거부 확인.

### T14 — 통합 인수·성능·현장 시험 (N01~N11)

파일: acceptance-report.md, 기존 테스트 확장.

- [ ] 아래 인수 시나리오를 mock에서 전부 실행하고 실물 가능 항목을 현장 담당과 수행한다.
- [ ] 지도+영상 2개+기록 동시 부하로 p95/실제 FPS/메모리/큐·디스크를 측정한다.
- [ ] 요구사항 ID마다 PASS/FAIL/NOT_RUN 및 증거를 표로 작성한다.
- [ ] 실패 항목을 수정한 후 해당 검증을 재실행한다. 하드웨어 미검증은 NOT_RUN으로 남긴다.

## 5. 인수 시나리오

| ID | 실행 | 기대 결과 |
|---|---|---|
| A01 | 로봇 없이 mock 실행 | 지도 2개 마커, 지도 아래 두 영상, MOCK 표식 |
| A02 | 목표 1개 설정·편대 출발·도착 | 추종 준비 이후 마스터 출발, 양쪽 완료 후 임무 성공 |
| A03 | 슬레이브 추종 준비 거절 | 마스터 목표 미전송, 이유 표시 |
| A04 | 주행 중 전체 정지, 한쪽 무응답 | 응답한 로봇 정지 확인, 다른 로봇 UNCONFIRMED, 전체 성공 미표시 |
| A05 | 수동 입력 중 키 해제·탭 전환·브라우저 종료 | 입력 중단, 모의/로봇 watchdog 정지, 재연결 자동 주행 없음 |
| A06 | 슬레이브 통신/추종 상실 | 경고·편대 정지, 복구 후 명시적 재합류 필요 |
| A07 | 카메라 1개 중단 | 해당 타일만 경고·가림, 다른 영상·지도 지속 |
| A08 | 동일 명령 재전송·늦은 수락 | 중복 실행 없음, 결과 재조정 기록 |
| A09 | 3지점 2회 순찰·일시정지·재개 | 순서/회차 일치, 중간 실패를 성공으로 건너뛰지 않음 |
| A10 | 위치 stale, 배터리 정상 5초 주기 | 위치만 stale, 배터리 잘못된 오프라인 판정 없음 |
| A11 | 지도 원점 회전·확대 후 클릭 | world 목표 좌표 정확, 지도/카메라 로봇 선택 일치 |
| A12 | 이력 필터·녹화 재생·공백 탐색 | 이벤트·두 궤적·영상 정렬, 공백 표시, 실물 명령 없음 |
| A13 | 다른 사용자 제어·관찰자 POST | 제어권 충돌 409/권한 403, 운영자 긴급정지는 허용 |
| A14 | 서버 재시작·디스크 부족 | 임무 PAUSED, 자동 출발 없음, 기록 중단 경고, 정지 경로 유지 |
| A15 | 두 namespace와 TF·실제 카메라 확인 | 데이터/명령 교차 없음, 공통 좌표 기반 간격 |
| A16 | 지도/설정/LED 변경·미지원 서비스 | 정지 조건·버전 검사, 수락과 완료 구별, 미지원 표시 |

실물 주행 시험은 저속·확보된 공간에서 현장 담당자가 물리 정지 수단과 함께 수행한다. 초기 제한값은 제안값이므로 실제 정지 거리와 추종 오차를 기록해 확정한다.

## 6. 순서·일정 추정·추적표

단독 개발자 기준 예상 23~35 작업일이며 실물 인터페이스가 준비되지 않은 대기 시간은 별도다. 확정 납기나 성능 보장이 아니다.

| 구간 | 작업 | 예상 | 완료 산출물 |
|---|---|---|---|
| 기반·화면 | T01~T04 | 5~7일 | 두 로봇 모의 지도·영상 대시보드 |
| 제어·임무 | T05~T07 | 5~8일 | 정지·추종·단일/순찰 임무 |
| 운영 기능 | T08~T11 | 6~9일 | 알림·설정·이력·동기 재생 |
| 실물·배포·인수 | T12~T14 | 7~11일 | 연동 보고서·실행 문서·인수 결과 |

T12의 인터페이스 조사는 T01 직후 시작해 로봇 담당에게 계약을 전달할 수 있다. 본격 ROS 연동은 mock 제어 검증 후 수행한다. MVP는 T01~T06, T08의 핵심 알림 및 T12의 해당 실물 연동을 통과한 상태이며, 전체 범위 완료와 구분한다.

| 요구사항 | 구현 작업 |
|---|---|
| R01/R02/R03 | T01/T02/T03/T12 |
| R04/R06/R08 | T06/T12 |
| R05 | T04/T12 |
| R07 | T07 |
| R09/R10/R18 | T02/T05/T12 |
| R11/R12 | T08/T12 |
| R13 | T10 |
| R14 | T11 |
| R15/R16/R17 | T09/T12 |
| R19 | T01 및 각 기능 mock 시나리오 |
| N01/N02/N07/N08 | T03/T04/T14 |
| N03/N06 | T05/T12/T14 |
| N04/N05 | T02/T07/T13/T14 |
| N09 | T02/T13/T14 |
| N10/N11 | T10/T11/T14 |

## 7. 최종 완료 정의

모든 R/N 항목에 검증 증거가 있고 mock/ROS/실물 결과를 구별해 인수 보고서를 제출한다. 모든 예정 화면·API·설정·테스트·실행 문서를 제공한다. 실물 카메라/추종/정지 계약 미충족을 숨기지 않는다. 남은 항목이 있는 경우 구현 완료 범위와 정확한 외부 의존성을 명시한다.
