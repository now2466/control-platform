# 구현 계약 보완

이 문서는 명세 검토에서 확인한 API 세부 사항을 보완한다. 구현자는 다른 문서와 함께 읽고 아래 규칙을 우선 적용한다.

## 추종 시작

기능 명세의 READY/PAUSED → FOLLOWING 전이에서 start/resume는 임무의 start/resume를 뜻한다. `/formation/actions`는 pair/pause/unpair/rejoin만 받는다. 추종 준비 및 시작은 임무 시작 절차 내부에서 로봇 FollowCommand의 start를 호출해 수행한다. 별도의 관제 formation start API는 구현하지 않는다. 따라서 준비만 된 상태와 실제 추종 중 상태를 혼동하지 않는다.

## 로봇 등록·역할 변경 API

- `PUT /api/v1/robots/{id}`: request_id, version, name, namespace, topic_mapping, frame_mapping을 받는다. 관리자만 실행하며 두 로봇 정지 및 편대 해제 상태가 필요하다. ID는 robot_1/robot_2만 허용하고 중복 namespace를 거부한다. 응답은 적용된 설정과 새 version이다. 설정 실패 시 기존 활성 값을 유지한다.
- `POST /api/v1/formation/roles`: request_id, master_id, slave_id를 받는다. 서로 다른 등록 ID와 양쪽 정지·편대 해제를 검증한다. 응답은 command이며 완료 후 지도·영상·카드 역할을 한 스냅샷에서 갱신한다.
- T09에서 위 API와 관리자 화면을 구현하고 test_settings.py에서 이동 중 변경 거부·중복 namespace·역할 교환을 검증한다.

## 지도 센서 레이어 실시간 계약

상태 WS의 type에 map/path/scan/costmap을 추가한다. 레이어 payload는 공통 robot_id, frame_id, source_at, received_at을 포함한다.

- path: points 배열, 각 원소는 x,y(m).
- scan: 공통 map 좌표로 변환한 points(x,y) 최대 2000개, 최대 5Hz.
- costmap: resolution,width,height,origin,data(0~255 배열), 최대 1Hz.
- map: map_id,version으로 지도 API 재조회를 유도한다.

클라이언트는 `{type:"subscribe_layers",robot_id,layers:["path","scan","costmap"]}`로 선택 로봇의 레이어를 구독한다. 선택되지 않은 scan/costmap은 전송하지 않는다. TF 변환 실패 시 빈 레이어와 reason_code를 전달하고 기존 레이어를 지운다. T03/T08/T12에서 각 생산·표시·ROS 매핑을 구현한다.

## 임무 시작 및 취소 완료

임무 validate는 DRAFT → READY, 실패 시 DRAFT 유지 및 이유 반환이다. 목표 편집은 READY를 DRAFT로 되돌린다. STARTING에서 한쪽 준비 실패는 FAILED이며 양쪽 보호 정지를 요청한다. pause/cancel 중 정지를 확인하지 못하면 PAUSING/CANCELING 상태를 유지하고 UNCONFIRMED 경고를 표시한다. 정지 확인 전 PAUSED/CANCELED로 표시하지 않는다.

## 준비 자료 읽기 순서

README → 요구사항 정의서 → 기능 명세서 → 이 보완 문서 → 구현 계획 순서로 읽는다. 구현 계획의 T01 모델 정의와 T06 상태 전이 테스트에 이 문서의 규칙을 포함한다.
