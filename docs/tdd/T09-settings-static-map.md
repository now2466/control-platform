# T09 — 설정·정적 지도·초기 위치 TDD 기록

## 범위

이번 단계는 mock 운용 설정만 다룬다. 활성 정적 지도 선택, 추종 거리·허용 오차, 최대 선/각속도, 카메라 품질(`low`/`default`/`high`)을 SQLite의 단일 활성 설정으로 저장한다. `PUT /api/v1/settings`는 화면이 읽은 `version`을 비교해 갱신하며, 오래된 버전은 `409 SETTINGS_VERSION_CONFLICT`로 거절한다.

초기 위치는 선택한 로봇이 ONLINE·FRESH이고 IDLE/STOPPED, 속도 0, 정지 래치 해제, 편대 해제 상태일 때만 `POST /api/v1/robots/{robot_id}/initial-pose`로 접수한다. 기존 command request_id 저장소를 사용하므로 같은 요청은 한 번만 adapter에 전달된다. 설정과 초기 위치 변경은 ADMIN 권한·Origin·CSRF 검증을 모두 요구한다.

SLAM 지도 생성/저장/리셋, LED·lamp·LCD/감정 장치, 역할 교환·로봇 등록 및 실제 ROS 매핑은 이번 축소 범위에 포함하지 않는다. ROS 설정 적용은 T12에서 실제 인터페이스 계약을 확인한 뒤 구현한다.

## RED

- `backend/tests/test_t09_settings.py`에서 관리자 권한, version 충돌, 수치 경계, mock 부분 적용 실패 시 이전 활성값 유지, 정지 상태 초기 위치와 중복 request_id를 먼저 작성했다.
- `frontend/src/SettingsPage.test.tsx`에서 API가 반환한 version을 PUT body에 보존하고, 선택 로봇의 초기 위치 요청 및 VIEWER 비활성 UI를 먼저 작성했다.
- 정적 지도 두 개를 노출하면서 기존 단일 지도 목록 assertion이 실패했고, 목록 계약을 두 static map 항목으로 명시적으로 갱신했다.

## GREEN

- migration 006의 `active_settings` compare-and-swap과 `SettingsService`가 mock adapter의 pair-wide 적용 성공 뒤에만 새 설정을 저장한다.
- map 선택은 이동 중이거나 편대/임무가 활성인 경우 거절한다. initial pose도 별도의 정지 검증을 통과해야 한다.
- `SettingsPage`는 활성 지도, 모든 제한값, 품질, 선택 로봇 pose 입력을 표시하고 ADMIN 외 사용자에게 변경을 비활성화한다.

## 검증

```text
backend/.venv/bin/python -m pytest -q
frontend/npm run test
frontend/npm run build
```

mock adapter 검증은 실제 로봇 설정 또는 초기 위치 적용의 증거가 아니다. T12에서 로봇별 ROS command/status 계약, 하드웨어 속도 상한, 실제 map frame을 별도로 확인해야 한다.
