from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from pinky_control_center.models import (
    Alert,
    AlertSeverity,
    AlertState,
    Connection,
    FormationMode,
    Freshness,
    SensorState,
    StateSnapshot,
)


class AlertService:
    """Turns current observations into one durable alert per code and robot.

    The service only returns newly activated alerts.  Runtime safety actions can
    therefore react once without turning each 5 Hz observation into a stop storm.
    """

    def __init__(self, storage, clock: Callable[[], datetime] | None = None) -> None:
        self.storage = storage
        self.clock = clock or (lambda: datetime.now(UTC))
        self._alerts = {(alert.code, alert.robot_id): alert for alert in storage.alerts(limit=1000)[0]}
        self._active_since: dict[tuple[str, str | None], datetime] = {}
        self._clear_since: dict[tuple[str, str | None], datetime] = {}

    def list(self, *, state: str | None = None, severity: str | None = None, robot_id: str | None = None, limit: int = 100, cursor: int = 0) -> list[Alert]:
        wanted = AlertState(state) if state is not None else None
        return self.storage.alerts(state=wanted, severity=severity, robot_id=robot_id, limit=limit, cursor=cursor)[0]

    def page(self, *, state: str | None = None, severity: str | None = None, robot_id: str | None = None, limit: int = 100, cursor: int = 0) -> tuple[list[Alert], int | None]:
        wanted = AlertState(state) if state is not None else None
        return self.storage.alerts(state=wanted, severity=severity, robot_id=robot_id, limit=limit, cursor=cursor)

    def get(self, alert_id: str) -> Alert | None:
        return self.storage.alert(alert_id)

    def acknowledge(self, alert_id: str, username: str) -> Alert | None:
        alert = self.storage.acknowledge_alert(alert_id, username)
        if alert is not None:
            self._alerts[(alert.code, alert.robot_id)] = alert
            self.storage.record_history_safe(event_type="ALERT_ACK", robot_id=alert.robot_id, mission_id=str(alert.mission_id) if alert.mission_id else None, payload={"alert_id": str(alert.alert_id), "code": alert.code, "acknowledged_by": username}, dedupe_key=f"alert:{alert.alert_id}:ack:{alert.acknowledged_at.isoformat() if alert.acknowledged_at else username}")
        return alert

    def _condition(self, code: str, robot_id: str | None, severity: AlertSeverity, message: str, active: bool, *, activate_after: timedelta = timedelta(0), clear_after: timedelta = timedelta(seconds=3), clear_when: bool | None = None) -> Alert | None:
        now, key = self.clock(), (code, robot_id)
        current = self._alerts.get(key)
        is_active = current is not None and current.state is AlertState.ACTIVE
        if active:
            self._clear_since.pop(key, None)
            if not is_active:
                started = self._active_since.setdefault(key, now)
                if now - started < activate_after:
                    return None
                alert = Alert(alert_id=(current.alert_id if current else uuid4()), code=code, robot_id=robot_id, severity=severity, state=AlertState.ACTIVE,
                              occurrences=(current.occurrences + 1 if current else 1), message=message,
                              first_seen_at=(current.first_seen_at if current else now), last_seen_at=now,
                              acknowledged_at=None, acknowledged_by=None)
                self._alerts[key] = self.storage.upsert_alert(alert)
                self.storage.record_history_safe(event_type="ALERT_ACTIVE", robot_id=robot_id, mission_id=str(alert.mission_id) if alert.mission_id else None, payload={"alert_id": str(alert.alert_id), "code": code, "severity": severity.value, "message": message}, dedupe_key=f"alert:{alert.alert_id}:active:{alert.occurrences}")
                return alert
            self._active_since.pop(key, None)
            # Deduplicate UI events: repeated observations only refresh last_seen.
            alert = current.model_copy(update={"last_seen_at": now, "message": message, "severity": severity})
            self._alerts[key] = self.storage.upsert_alert(alert)
            return None
        self._active_since.pop(key, None)
        if not is_active or clear_when is False:
            return None
        started = self._clear_since.setdefault(key, now)
        if now - started < clear_after:
            return None
        alert = current.model_copy(update={"state": AlertState.RESOLVED, "last_seen_at": now})
        self._alerts[key] = self.storage.upsert_alert(alert)
        self.storage.record_history_safe(event_type="ALERT_RESOLVED", robot_id=robot_id, mission_id=str(alert.mission_id) if alert.mission_id else None, payload={"alert_id": str(alert.alert_id), "code": code, "severity": alert.severity.value}, dedupe_key=f"alert:{alert.alert_id}:resolved:{alert.last_seen_at.isoformat()}")
        self._clear_since.pop(key, None)
        return None

    def evaluate(self, snapshot: StateSnapshot) -> list[Alert]:
        created: list[Alert] = []
        for robot in snapshot.robots:
            def add(*args, **kwargs) -> None:
                alert = self._condition(*args, **kwargs)
                if alert is not None:
                    created.append(alert)

            add("COMMUNICATION_LOSS", robot.robot_id, AlertSeverity.CRITICAL, "로봇 통신이 끊겼습니다.", robot.connection is Connection.OFFLINE)
            add("COMMUNICATION_STALE", robot.robot_id, AlertSeverity.WARNING, "로봇 heartbeat가 지연되었습니다.", robot.connection is Connection.STALE)
            add("TF_INVALID", robot.robot_id, AlertSeverity.CRITICAL, "TF 변환을 확인할 수 없습니다.", not robot.tf_valid)
            add("POSE_STALE", robot.robot_id, AlertSeverity.WARNING, "위치 데이터가 지연되었거나 없습니다.", robot.pose is None or robot.pose_freshness is not Freshness.FRESH)
            # A stale battery is not evidence of either a low or recovered battery.
            battery_fresh = robot.battery_percent is not None and robot.battery_freshness is Freshness.FRESH
            add("BATTERY_WARNING", robot.robot_id, AlertSeverity.WARNING, "배터리가 20% 이하입니다.", bool(battery_fresh and robot.battery_percent <= 20), activate_after=timedelta(seconds=10), clear_after=timedelta(seconds=10), clear_when=bool(battery_fresh and robot.battery_percent > 25))
            add("BATTERY_CRITICAL", robot.robot_id, AlertSeverity.CRITICAL, "배터리가 10% 이하입니다. 편대를 정지해야 합니다.", bool(battery_fresh and robot.battery_percent <= 10), activate_after=timedelta(seconds=10), clear_after=timedelta(seconds=10), clear_when=bool(battery_fresh and robot.battery_percent > 25))
            for sensor in robot.sensors:
                # Unsupported is a capability result, not a fault; it remains visible in sensor detail.
                if sensor.state is SensorState.UNSUPPORTED:
                    continue
                label = sensor.name
                error_code = "NAVIGATION_SENSOR_ERROR" if label in {"scan", "odom", "local_costmap", "global_costmap", "control"} else "SENSOR_ERROR"
                add(error_code, robot.robot_id, AlertSeverity.CRITICAL, f"필수 센서 {label} 상태가 ERROR입니다.", sensor.state is SensorState.ERROR)
                add("SENSOR_STALE", robot.robot_id, AlertSeverity.WARNING, f"센서 {label} 데이터가 지연되었습니다.", sensor.state is SensorState.STALE)
        add = lambda *args, **kwargs: created.append(alert) if (alert := self._condition(*args, **kwargs)) is not None else None
        add("FOLLOW_LOST", "robot_2", AlertSeverity.CRITICAL, "슬레이브 추종 상태가 LOST입니다.", snapshot.formation.state is FormationMode.LOST)
        return created

    def record_command_rejection(self, robot_id: str, reason_code: str | None) -> bool:
        message = f"명령이 거부되었습니다: {reason_code or 'UNKNOWN'}"
        alert = self._condition("COMMAND_REJECTED", robot_id, AlertSeverity.WARNING, message, True)
        return alert is not None

    def record_protective_stop_unconfirmed(self, reason: str, robot_ids: list[str]) -> bool:
        targets = ", ".join(robot_ids) or "unknown"
        alert = self._condition("PROTECTIVE_STOP_UNCONFIRMED", None, AlertSeverity.CRITICAL, f"보호 정지를 확인하지 못했습니다 ({reason}): {targets}", True)
        return alert is not None
