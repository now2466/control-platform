# T04 카메라 그리드 TDD 기록

범위는 인증된 카메라 WebSocket 중계와 모의 프레임이다. T05 제어와 녹화는 포함하지 않는다. 기존 `GET /api/v1/cameras/{robot_id}` JPEG snapshot은 하위 호환을 위해 유지하며, 인증이 필요하고 `camera_stall`인 `robot_2`만 503을 반환한다.

| 테스트 | RED 명령 및 실제 실패 이유 | GREEN 명령 및 결과 |
|---|---|---|
| `test_camera_websocket_sends_framed_jpeg_metadata` | `cd backend && .venv/bin/python -m pytest tests/test_cameras.py::test_camera_websocket_sends_framed_jpeg_metadata -q` → `/ws/cameras/...` 라우트가 없어 handshake가 close code 1000으로 끝남 | 같은 명령 → `1 passed`. 4-byte big-endian 길이, JSON metadata, JPEG SOI를 확인한다. |
| `test_camera_socket_rejects_unauthenticated_bad_origin_unknown_robot_and_quality` | `cd backend && .venv/bin/python -m pytest tests/test_cameras.py::test_camera_socket_rejects_unauthenticated_bad_origin_unknown_robot_and_quality -q` → 잘못된 `quality`가 FastAPI 기본 validation close `1008`이어서 기대한 명시적 `4400`과 불일치 | 같은 명령 → `1 passed`. 세션/Origin/로봇 ID/품질을 각각 4401/4403/4404/4400으로 거부한다. |
| `test_latest_frame_queue_drops_old_frame_throttles_and_cleans_up` | 기존 service 구현 뒤 추가한 특성 보완 테스트이므로 RED 실행은 없다. fake clock으로 default 10 FPS throttle, maxsize 1에서 최신 프레임 교체, viewer 해제를 검증한다. | `cd backend && .venv/bin/python -m pytest tests/test_cameras.py::test_latest_frame_queue_drops_old_frame_throttles_and_cleans_up -q` → `1 passed`. |
| `test_quality_resizes_low_but_never_upscales_high` | 기존 resize 구현 뒤 추가한 특성 보완 테스트이므로 RED 실행은 없다. | `cd backend && .venv/bin/python -m pytest tests/test_cameras.py::test_quality_resizes_low_but_never_upscales_high -q` → `1 passed`. low는 320×240, high는 640×480 source를 유지한다. |

프런트엔드 decoder/grid/stall 표시의 RED/GREEN 증거는 해당 구현 담당이 전달하면 이 문서에 같은 형식으로 추가한다. 모든 결과는 실제 실행 결과만 기록한다.

| 프런트엔드 테스트 | 기록 |
|---|---|
| `camera.test.ts`의 `decodes big endian metadata and JPEG payload`, `rejects malformed and oversized metadata safely` | decoder 구현 뒤 추가한 특성 보완 테스트다. `cd frontend && npm run test -- --run` → 기존 실행에서 `17 passed`. metadata 크기, JPEG SOI/EOI와 malformed 입력 거부를 확인한다. |
| `CameraGrid.test.tsx`의 `renders master before slave and hides only stalled tile after five seconds` | grid 구현 뒤 추가한 특성 보완 테스트다. 같은 명령 → 기존 실행에서 `17 passed`. master-first 순서와 5초 가림 문구를 확인한다. |
| `CameraGrid.test.tsx`의 `renders only JPEG bytes and reports measured FPS`, `does not reorder the caller robot array` | 구현 뒤 검토 보완으로 추가한 validation 테스트이므로 RED 실행은 없다. | `cd frontend && npm run test -- --run src/CameraGrid.test.tsx` → `4 passed`. JPEG slice 경계, 1초 창 FPS, props 배열 비변경을 확인한다. |
| `CameraGrid.test.tsx`의 `supports quality selection and marks session expiry` | `cd frontend && npm run test -- --run src/CameraGrid.test.tsx` → `화질` label을 찾지 못해 quality selector 부재 assertion이 실패했다. | 같은 명령 → 당시 `2 passed`; 현재 전체 frontend 검증에서는 `19 passed`. |
