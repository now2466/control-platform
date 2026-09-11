# T06 편대·단일 목표 임무 TDD 기록

T06은 mock adapter의 명령 기록으로 순서를 검증한다. ROS action 결과·실제 정지는 T12 범위이며, 여기서는 adapter acceptance와 state observation 계약을 구현한다.

| 테스트 | RED 증거 | GREEN 결과 |
|---|---|---|
| `test_pair_requires_ready_robots_and_transitions_to_ready` | 이 세션의 최초 실행은 system Python으로 실행해 FastAPI가 없어 수집 단계에서 실패했다. 이는 route RED 증거가 아니므로 route RED로 기록하지 않는다. | venv의 같은 실제 경로가 202 command를 만들고 dispatcher 처리 뒤 `UNPAIRED → READY`가 된다. pair는 두 로봇 ONLINE, 정지 래치 해제, 유효 TF/pose, 마스터 navigate와 슬레이브 follow capability를 검사한다. |
| `test_mission_start_sends_slave_ready_and_follow_before_master_navigation` | 최초 GREEN 후보에서 `GET /missions/{id}`가 mutation dependency를 사용해 403이었고 test는 `KeyError: state`로 실패했다. | GET을 authenticated read dependency로 바꾼 뒤 start 처리의 recorded adapter calls가 `robot_2 follow_ready`, `robot_2 follow_start`, `robot_1 navigate` 순서임을 검사한다. slave 거절/예외 시 master navigate 없이 양쪽 stop을 요청한다. |
| `test_pause_is_transitional_until_both_stop_observations_confirm` | 초기 구현은 pause adapter 접수 직후 PAUSED로 전이했다. | pause/cancel은 PAUSING/CANCELING에 머물고, 두 로봇의 latch와 0 속도를 관측한 runtime tick 뒤에만 PAUSED/CANCELED로 전이한다. |
| `test_master_success_without_slave_settle_pauses_after_ten_fake_seconds` | master 완료 뒤 slave settle 대기 상태가 없었다. | fake monotonic clock에서 master 완료 9.99초 뒤 RUNNING, 10초에 `SLAVE_SETTLE_TIMEOUT` PAUSED를 확인한다. 실제 ROS action result hook은 T12에서 `master_navigation_succeeded`에 연결한다. |
| `frontend/src/T06.test.tsx` | 패널 초안은 App과 지도 목표 상태에 연결되지 않았고 실제 create → validate → start API 흐름과 lease/READY gate를 검증하는 테스트 3개가 실패했다. 편대 pause/unpair 테스트도 버튼 부재로 실패했으며, 202 직후 단일 mission 조회 테스트는 dispatcher 지연에서 timeout/오류 assertion으로 실패했다. | 지도 목표를 App과 mission 패널에 연결했다. 편대 action과 mission action은 실제 API를 호출하며 상태와 lease에 따라 버튼을 제한한다. 202 응답의 command ID를 terminal 상태까지 제한 시간 동안 조회한 뒤 mission을 갱신하고 실패·거절·시간 초과를 화면 오류 영역에 전달한다. |

검증: `cd backend && .venv/bin/python -m pytest -q` → **56 passed**, `cd frontend && npm test` → **33 passed**, `cd frontend && npm run build` → **성공** (2026-09-11).

SQLite migration 004는 mission payload/state를 저장한다. command의 기존 24시간 request-id idempotency와 dispatcher 경로를 formation/mission actions에 계속 사용하며, 동시 mission 생성도 하나의 mission ID로 원자적으로 수렴한다.

리뷰 보완 후 mission 생성도 command idempotency 저장소를 사용한다. formation/mission mutation은 유효한 control lease가 필요하며 payload `lease_id` 또는 UI가 전송하는 `X-Control-Lease-Id` 헤더로 소유권을 확인한다. mock adapter command 완료 이벤트는 runtime tick에서 소비되어 master navigate의 10초 slave-settle 대기를 시작한다.
