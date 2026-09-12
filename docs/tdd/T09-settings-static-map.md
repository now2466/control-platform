# T09 — 설정·정적 지도·초기 위치 TDD 기록

## 범위

이번 단계는 mock 운용 설정만 다룬다. 활성 정적 지도 선택, 추종 거리·허용 오차, 최대 선/각속도, 카메라 품질(`low`/`default`/`high`)을 SQLite의 단일 활성 설정으로 저장한다. `PUT /api/v1/settings`는 화면이 읽은 `version`을 비교해 갱신하며, 오래된 버전은 `409 SETTINGS_VERSION_CONFLICT`로 거절한다.

관리자용 초기 위치는 선택한 로봇이 ONLINE·FRESH이고 IDLE/STOPPED, 속도 0, 정지 래치 해제, 편대 해제 상태일 때만 `POST /api/v1/robots/{robot_id}/initial-pose`로 접수한다. 현장 시험용 `POST /api/v1/robots/{robot_id}/localization-reset`은 operator lease를 요구하고, 로봇을 들어 옮긴 뒤 기존 map pose/TF가 stale 또는 unknown이어도 연결·정지·속도 0이면 활성 정적 지도의 자유 셀 pose를 `/initialpose`로만 전달한다. 같은 요청은 한 번만 adapter에 전달되며 두 API 모두 자동 주행을 시작하지 않는다. 설정 변경은 ADMIN 권한·Origin·CSRF 검증을 모두 요구하고, localization reset/navigation은 OPERATOR 이상 권한과 lease를 요구한다.

SLAM 지도 생성/저장/리셋은 정적 `map_260905` 운용 범위에 포함하지 않는다. 로봇을 수동 재배치할 때는 지도 대신 AMCL pose를 재설정하며, Nav2 연결은 T15에서 별도 구현한다. LED·lamp·LCD/감정 장치, 역할 교환·로봇 등록 및 기타 실제 ROS 매핑은 실제 인터페이스 계약 확인 뒤 구현한다.

## RED

- `backend/tests/test_t09_settings.py`에서 관리자 권한, version 충돌, 수치 경계, mock 부분 적용 실패 시 이전 활성값 유지, 정지 상태 초기 위치와 중복 request_id를 먼저 작성했다.
- `frontend/src/SettingsPage.test.tsx`에서 API가 반환한 version을 PUT body에 보존하고, 선택 로봇의 초기 위치 요청 및 VIEWER 비활성 UI를 먼저 작성했다.
- 정적 지도 두 개를 노출하면서 기존 단일 지도 목록 assertion이 실패했고, 목록 계약을 두 static map 항목으로 명시적으로 갱신했다.

## GREEN

- migration 006의 `active_settings` compare-and-swap과 `SettingsService`가 mock adapter의 pair-wide 적용 성공 뒤에만 새 설정을 저장한다.
- map 선택은 이동 중이거나 편대/임무가 활성인 경우 거절한다. initial pose도 별도의 정지 검증을 통과해야 한다.
- `SettingsPage`는 활성 지도, 모든 제한값, 품질, 선택 로봇 pose 입력을 표시하고 ADMIN 외 사용자에게 변경을 비활성화한다.
- 임무 생성은 현재 활성 static map만 받으며, pair/follow-start와 slave settle은 저장된 거리·허용 오차를 사용한다. manual WebSocket도 저장된 선/각속도를 초과하면 `SETTINGS_SPEED_LIMIT`으로 거절한다.
- 임무 생성은 READY 편대의 검증된 master/slave pair가 있어야 한다. start/resume도 저장된 map_id와 pair가 현재 활성 지도·편대와 일치하는지 다시 검사하므로, map 변경 뒤 남은 draft/READY mission을 주행시킬 수 없다.
- `mock_lab_b`는 별도 deterministic occupancy PNG를 제공한다. 두 map은 이름, ETag, 픽셀 fixture가 같지 않다.
- camera quality는 SettingsPage가 읽은 활성값으로 모든 CameraTile을 초기화하고, 서버 lifespan에서 저장된 설정을 mock adapter에 다시 적용한다. 재시작 뒤에도 새 frame과 UI가 여는 camera socket이 같은 품질을 사용한다.

## 검증

```text
backend/.venv/bin/python -m pytest -q
frontend/npm run test
frontend/npm run build
```

mock adapter 검증은 실제 로봇 설정 또는 초기 위치 적용의 증거가 아니다. T12에서 로봇별 ROS command/status 계약, 하드웨어 속도 상한, 실제 map frame을 별도로 확인해야 한다.

설정 apply의 adapter 상태와 SQLite 상태를 한 process에서 함께 유지해야 하므로 서비스는 단일 worker만 지원한다. CLI는 `workers=1`로 실행하며 `CONTROL_PLATFORM_WORKERS`가 1 이외의 값이면 시작을 거절한다. 다중 worker 배포는 T13에서 process 간 adapter ownership/coordination을 추가한 뒤에만 허용한다.
