# T08 — 알림·센서 상세

범위는 mock 관측에서의 알림과 선택 로봇의 지도 센서 오버레이다. ROS `LaserScan`/`Costmap` 구독과 실제 필수 노드 graph 검증은 T12 범위다. mock은 `robot_1`의 Scan·local/global costmap만 최소 데이터로 표시하고, `robot_2`는 `UNSUPPORTED` 상태를 명시한다.

| 테스트 | RED 명령 및 실제 실패 이유 | GREEN 결과 |
|---|---|---|
| `backend/tests/test_alerts.py` | `cd backend && .venv/bin/python -m pytest tests/test_alerts.py -q` → `ModuleNotFoundError: pinky_control_center.alert_service` | 같은 명령 → 4 passed. 저/위험 배터리의 10초 지속·10초 해소, stale 배터리 미판정, ACTIVE ACK, 통신·TF·추종·센서·명령 거절 중복 억제와 follow LOST의 한 번뿐인 양쪽 보호 정지를 확인한다. |
| `frontend/src/T08.test.tsx` | `cd frontend && npm test -- --run src/T08.test.tsx` → `AlertList`가 없어 import 해석 실패 | 같은 명령 → 2 passed. ACK 후에도 ACTIVE 원인이 보이는 것과 선택 로봇의 Scan/costmap 전환·UNSUPPORTED 표시를 확인한다. |

`AlertService`는 `(code, robot_id)`별 단일 활성 알림을 유지한다. 반복 관측은 `last_seen_at`만 갱신하고 새 팝업/보호 정지를 만들지 않는다. 일반 통신·TF·센서·추종 경고는 정상 상태가 3초 이어져야 해소한다. 배터리는 FRESH 값만 사용하며 20%/10% 이하와 25% 초과 해소에 각각 10초 hysteresis를 적용한다. ACK는 확인자·시각만 기록하며 ACTIVE 원인을 RESOLVED로 바꾸지 않는다.

런타임은 새 `FOLLOW_LOST`, `TF_INVALID`, `SENSOR_ERROR`, `BATTERY_CRITICAL`에만 편대 보호 정지를 요청한다. 카메라 중단은 T04의 영상 경고에 맡기며 로봇을 자동 정지하지 않는다. sensor detail API의 `UNSUPPORTED`와 `STALE`은 값 대신 상태로 응답하고, 프런트엔드는 각각 `지원하지 않음`·`데이터 지연`으로 표시한다.

검증: `cd backend && .venv/bin/python -m pytest -q` → 70 passed, `cd frontend && npm test -- --run` → 45 passed, `cd frontend && npm run build` → 성공 (2026-09-11).
