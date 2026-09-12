# T08 — 알림·센서 상세

범위는 mock 관측에서의 알림과 선택 로봇의 지도 센서 오버레이다. ROS `LaserScan`/`Costmap` 구독과 실제 필수 노드 graph 검증은 T12 범위다. mock은 `robot_1`의 Scan·local/global costmap만 최소 데이터로 표시하고, `robot_2`는 `UNSUPPORTED` 상태를 명시한다.

T12 실물 연동 보완으로 rosbridge `/scan`을 최대 5Hz로 구독하고 LaserScan frame을 map frame으로 변환한 점을 지도 위에 표시한다. Scan 화면을 연 동안만 상세 API를 200ms 간격으로 갱신하며, 근거리 반사점 색상·최근접 거리·점 개수로 차체 반사와 벽 오인식을 현장에서 확인할 수 있게 한다.

| 테스트 | RED 명령 및 실제 실패 이유 | GREEN 결과 |
|---|---|---|
| `backend/tests/test_alerts.py` | `cd backend && .venv/bin/python -m pytest tests/test_alerts.py -q` → `ModuleNotFoundError: pinky_control_center.alert_service` | 같은 명령 → 4 passed. 저/위험 배터리의 10초 지속·10초 해소, stale 배터리 미판정, ACTIVE ACK, 통신·TF·추종·센서·명령 거절 중복 억제와 follow LOST의 한 번뿐인 양쪽 보호 정지를 확인한다. |
| `frontend/src/T08.test.tsx` | `cd frontend && npm test -- --run src/T08.test.tsx` → `AlertList`가 없어 import 해석 실패 | 같은 명령 → 2 passed. ACK 후에도 ACTIVE 원인이 보이는 것과 선택 로봇의 Scan/costmap 전환·UNSUPPORTED 표시를 확인한다. |

`AlertService`는 `(code, robot_id)`별 단일 활성 알림을 유지한다. 반복 관측은 `last_seen_at`만 갱신하고 새 팝업/보호 정지를 만들지 않는다. 일반 통신·TF·센서·추종 경고는 정상 상태가 3초 이어져야 해소한다. 배터리는 FRESH 값만 사용하며 20%/10% 이하와 25% 초과 해소에 각각 10초 hysteresis를 적용한다. ACK는 확인자·시각만 기록하며 ACTIVE 원인을 RESOLVED로 바꾸지 않고, 해소 뒤 재발하면 ACK 정보를 지운다.

리뷰 보완 RED는 기존 `test_alerts.py`에 추가했다. 활성 편대의 COMMUNICATION_LOSS/STALE는 보호 정지를 전혀 요청하지 않았고, 정지 확인 뒤 FOLLOW_LOST는 PAUSED가 되었다. 프런트엔드는 선택을 바꾼 뒤에도 이전 로봇 Scan을 표시했다. 동일 테스트는 보호 정지 1회, LOST 유지·ACK 초기화, 선택 ID 일치 레이어만 렌더링하는 GREEN 결과를 확인한다.

추가 안전 보완 RED는 보호 정지 adapter의 거절/예외가 pending 상태로 남는 것과, 일반 pause pending 중 새 FOLLOW_LOST가 PAUSED로 마무리되는 것을 재현했다. GREEN은 두 대상의 stop을 한 번씩 시도한 뒤 거절 대상을 `STOP_UNCONFIRMED`/`PROTECTIVE_STOP_UNCONFIRMED`으로 노출하고 pending을 해제한다. 이미 진행 중인 일반 pause에는 stop을 재전송하지 않고 FOLLOW_LOST 이유만 승격해 정지 확인 뒤 LOST와 rejoin 경로를 유지한다.

런타임은 새 통신 LOSS/STALE, `FOLLOW_LOST`, `TF_INVALID`, 주행 센서 ERROR, `BATTERY_CRITICAL`에만 편대 보호 정지를 요청한다. 카메라 같은 비주행 센서 ERROR는 경고만 남긴다. FOLLOW_LOST는 정지 확인 후에도 LOST를 유지해 명시적 rejoin 경로를 보존하고, 다른 원인은 PAUSED로 전이한다. sensor detail API의 `UNSUPPORTED`와 `STALE`은 값 대신 상태로 응답하고, 프런트엔드는 각각 `지원하지 않음`·`데이터 지연`으로 표시한다. 선택 변경 시 이전 로봇 레이어를 즉시 비우고 응답 `robot_id`가 현재 선택과 다르면 버린다.

현재 `FormationState.distance_m`에는 측정 유효성/신선도 계약이 없으므로, too-far/too-close 알림은 신뢰할 수 있는 입력을 만들지 않기 위해 추가하지 않았다. T12의 FollowStatus `measurement_valid`와 freshness 연결 뒤에 구현한다.

검증: `cd backend && .venv/bin/python -m pytest -q` → 74 passed, `cd frontend && npm test -- --run` → 46 passed, `cd frontend && npm run build` → 성공 (2026-09-11).
