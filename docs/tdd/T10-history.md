# T10 — 운용 이력·JSON 내보내기 TDD 기록

## 범위

SQLite `history_events`는 30일 보존의 작고 append-only인 운용 이벤트 스트림이다. 명령의 접수·실행·결과·종료 상태, 임무 생성/상태 전이, 편대 상태 전이, 알림의 ACTIVE/RESOLVED/ACK, 설정·활성 지도·초기 위치 요청과 보호 정지를 기록한다. 중복 관측·재시도는 이벤트별 안정 dedupe key 또는 저장된 이전 상태 비교로 한 번만 남긴다. 상태가 다시 바뀌어 같은 상태로 돌아오는 정상 cycle은 새 이력이다.

고속 telemetry, Scan/costmap, trail·navigation path, camera frame은 이력 payload에 저장하지 않는다. JSON export만 제공하며 CSV와 분석 기능은 이번 범위가 아니다.

## RED

- `backend/tests/test_t10_history.py`에서 명령 lifecycle/result 이력, 다른 사용자의 이력 비노출, robot/event filter·cursor, 101건 JSON export 완전성, 명시적 export cap, 그리고 임무·편대 반복 cycle/retry를 먼저 작성했다.
- 동일 테스트에서 audit writer를 실패시키고 watchdog 보호 정지를 호출해도 양쪽 stop adapter 호출이 끝까지 실행되는지를 작성했다.
- 같은 테스트에서 첫 stop adapter 예외 뒤에도 두 번째 stop을 호출하고, 실패 시도는 민감한 예외 원문 없이 `ADAPTER_EXCEPTION` 결과로 남기는지를 작성했다.
- `frontend/src/T10.test.tsx`에서 유형 filter 조회와 현재 filter를 보존하는 JSON 다운로드를 먼저 작성했다.

## GREEN

- migration 007은 owner, event type, robot/mission scope, UTC timestamp, 제한된 JSON payload를 저장한다. 각 write에서 30일보다 오래된 이벤트를 정리한다.
- `GET /api/v1/history`와 `/api/v1/history/export`는 인증을 요구하고, 사용자 소유 이벤트와 공통 안전/알림 이벤트만 반환한다. 기본 범위는 최근 24시간, 요청 가능 최대 범위는 30일이고 limit은 1~100이다. cursor는 마지막 event id다. export는 complete file만 반환하며 10,000건을 넘으면 `413 HISTORY_EXPORT_LIMIT`으로 명시적으로 거절한다.
- history writer는 SQLite 오류를 잡아 `audit history degraded` 경고만 기록한다. 제어 dispatcher와 보호 정지는 이 실패를 기다리거나 전파하지 않는다. watchdog stop은 `ACKNOWLEDGED`·`REJECTED`·`EXCEPTION` 결과를 구분해 남긴다.
- History UI는 event type·로봇·임무 ID·UTC 범위를 필터링하고 페이지를 이어 읽으며, 다운로드할 때도 100건 cursor page를 모두 이어 받아 최대 10,000건의 완전한 `history.json`을 만든다.

## 검증

```text
cd backend && .venv/bin/python -m pytest -q
cd frontend && npm test -- --run
cd frontend && npm run build
```

SQLite file 자체의 디스크 고장으로 기존 명령/임무의 본 저장이 실패하는 상황을 복구하는 기능은 추가하지 않았다. T10이 새로 추가한 감사 저장은 그 실패가 안전 stop 또는 adapter 호출을 막지 않도록 best-effort로 격리한다.
