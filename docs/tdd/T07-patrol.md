# T07 순찰 임무 TDD 기록

| 테스트 | RED | GREEN |
|---|---|---|
| `test_patch_ready_mission_versions_and_validates_waypoint_bounds` | PATCH route와 version field 이전에는 경로가 없었다. | lease 소유 operator가 DRAFT/READY mission을 version으로 편집하며, 성공 시 version 증가(READY는 DRAFT 재검증 필요 상태), stale version은 409이다. |
| `test_patrol_advances_three_waypoints_two_laps_from_mock_completion_events` | 최초 실행은 master의 첫 navigate만 기록해 기대 `[1,2,3,1,2,3]`과 불일치했다. | mock navigate completion event → runtime tick → slave fresh stopped + target gap 확인 뒤 다음 goal을 전송한다. 3 지점×2 lap 순서와 최종 SUCCEEDED/index persistence를 확인한다. |
| `frontend/src/T07.test.tsx` waypoint 편집·생성 | 첫 구현은 새 지도 목표를 기존 목록에 누적하지 않아 3개 경유점 assertion과 전체 waypoint 생성 payload assertion이 실패했다. | 지도 목표를 최대 100개까지 누적하고 순서 변경·삭제·반복 횟수와 함께 실제 생성 API에 전송한다. |

검증: `cd backend && .venv/bin/python -m pytest -q` → **66 passed**, `cd frontend && npm test` → **43 passed**, `cd frontend && npm run build` → **성공** (2026-09-11).

API: `PATCH /api/v1/missions/{id}`는 `{request_id, lease_id 또는 X-Control-Lease-Id, version, name?, waypoints?, repeat_count?}`를 받는다. 허용 waypoint/repeat 범위는 각각 1~100이다.

추가 회귀: 동일 PATCH request_id/payload는 저장된 mission 결과를 replay하고 version을 한 번만 올리며, 바뀐 payload는 409이다. waypoint 2 navigate 거절은 mission을 FAILED로 저장하고 waypoint 3을 전송하지 않는다. pause/resume은 index/lap을 유지하고 같은 goal을 다시 보낸다. fake-clock settle timeout과 재시작은 PAUSED로 남으며 자동 navigate를 재개하지 않는다.

목록은 owner-scoped stable `created_at,id` 순서와 cursor/limit(1~100)로 제공한다. runtime tick은 master pose와 현재 goal 거리로 `progress_distance_m`를 저장한다. navigation 거절은 양쪽 stop을 요청하고 FAILED를 유지한다.

프런트엔드의 PATCH/version, command polling, 상태별 gating, 진행 표시, 409 오류, PAUSED 목록 복구 테스트는 구현 후 계약을 고정한 characterization/regression 증거다. terminal command 실패 뒤에도 mission을 다시 조회해 `FAILED`와 failure code, 현재 지점을 표시한다.
