from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4
import asyncio

from fastapi.testclient import TestClient

from pinky_control_center.alert_service import AlertService
from pinky_control_center.main import create_app
from pinky_control_center.models import (
    CommandAcceptance,
    Connection,
    FormationMode,
    Freshness,
    SensorState,
    SensorStatus,
    UserRole,
    MockScenario,
)
from pinky_control_center.adapters.mock import MockRobotAdapter
from pinky_control_center.storage import Storage


ORIGIN = "http://localhost:5173"


def snapshot_with(adapter, *, battery: float = 86, battery_freshness: Freshness = Freshness.FRESH, formation: FormationMode = FormationMode.UNPAIRED, tf_valid: bool = True, connection: Connection = Connection.ONLINE, sensor: SensorState = SensorState.OK):
    source = adapter.snapshot()
    robots = [source.robots[0].model_copy(update={"battery_percent": battery, "battery_freshness": battery_freshness, "tf_valid": tf_valid, "connection": connection, "sensors": [SensorStatus(name="scan", state=sensor, received_at=source.server_time)]}), source.robots[1]]
    return source.model_copy(update={"robots": robots, "formation": source.formation.model_copy(update={"state": formation})})


def test_battery_uses_ten_second_hysteresis_ignores_stale_and_ack_never_resolves(tmp_path: Path) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    storage = Storage(tmp_path / "control.db", clock=lambda: now)
    service = AlertService(storage, clock=lambda: now)
    adapter = MockRobotAdapter()
    low = snapshot_with(adapter, battery=8)
    assert service.evaluate(low) == []
    now += timedelta(seconds=9)
    assert service.evaluate(low) == []
    now += timedelta(seconds=1)
    created = service.evaluate(low)
    critical = next(alert for alert in created if alert.code == "BATTERY_CRITICAL")
    assert critical.state == "ACTIVE" and critical.occurrences == 1
    service.acknowledge(str(critical.alert_id), "operator")
    acknowledged = service.get(str(critical.alert_id))
    assert acknowledged is not None and acknowledged.state == "ACTIVE" and acknowledged.acknowledged_by == "operator"
    now += timedelta(seconds=30)
    service.evaluate(snapshot_with(adapter, battery=8, battery_freshness=Freshness.STALE))
    assert service.get(str(critical.alert_id)).state == "ACTIVE"
    high = snapshot_with(adapter, battery=30)
    service.evaluate(high)
    now += timedelta(seconds=10)
    service.evaluate(high)
    assert service.get(str(critical.alert_id)).state == "RESOLVED"
    storage.close()


def test_alerts_deduplicate_and_cover_communication_tf_follow_sensor_and_command_rejection(tmp_path: Path) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    storage = Storage(tmp_path / "control.db", clock=lambda: now)
    service = AlertService(storage, clock=lambda: now)
    adapter = MockRobotAdapter()
    broken = snapshot_with(adapter, formation=FormationMode.LOST, tf_valid=False, connection=Connection.OFFLINE, sensor=SensorState.ERROR)
    created = service.evaluate(broken)
    assert {alert.code for alert in created} >= {"COMMUNICATION_LOSS", "TF_INVALID", "FOLLOW_LOST", "NAVIGATION_SENSOR_ERROR"}
    service.evaluate(broken)
    communication = next(alert for alert in service.list(state="ACTIVE") if alert.code == "COMMUNICATION_LOSS")
    assert communication.occurrences == 1
    assert service.record_command_rejection("robot_1", "MOCK_COMMAND_REJECTED") is True
    assert service.record_command_rejection("robot_1", "MOCK_COMMAND_REJECTED") is False
    assert next(alert for alert in service.list(state="ACTIVE") if alert.code == "COMMAND_REJECTED").occurrences == 1
    unsupported = snapshot_with(adapter, sensor=SensorState.UNSUPPORTED)
    now += timedelta(seconds=3)
    service.evaluate(unsupported)
    assert not [alert for alert in service.list(state="ACTIVE") if alert.code == "SENSOR_UNSUPPORTED"]
    storage.close()


def login_headers(client: TestClient) -> dict[str, str]:
    client.app.state.storage.create_or_reset_user("operator", "operator-password", UserRole.OPERATOR)
    response = client.post("/api/v1/session", json={"username": "operator", "password": "operator-password"}, headers={"origin": ORIGIN})
    return {"origin": ORIGIN, "x-csrf-token": response.json()["csrf_token"]}


def test_alert_routes_keep_active_after_ack_and_sensor_layers_handle_supported_and_unsupported(tmp_path: Path) -> None:
    app = create_app(database_path=tmp_path / "control.db", start_watchdog=False)
    with TestClient(app) as client:
        headers = login_headers(client)
        app.state.alert_service.evaluate(snapshot_with(app.state.adapter, formation=FormationMode.LOST))
        alerts = client.get("/api/v1/alerts?state=ACTIVE").json()["items"]
        follow = next(alert for alert in alerts if alert["code"] == "FOLLOW_LOST")
        ack = client.post(f"/api/v1/alerts/{follow['alert_id']}/ack", json={"request_id": str(uuid4())}, headers=headers)
        assert ack.status_code == 200 and ack.json()["state"] == "ACTIVE" and ack.json()["acknowledged_by"] == "operator"
        assert client.get("/api/v1/alerts?state=ACTIVE").json()["items"]
        supported = client.get("/api/v1/robots/robot_1/sensor-layers").json()
        unsupported = client.get("/api/v1/robots/robot_2/sensor-layers").json()
        assert supported["scan"]["state"] == "OK" and supported["costmaps"][0]["state"] == "OK"
        assert unsupported["scan"]["state"] == "UNSUPPORTED"


def test_new_follow_lost_alert_requests_one_protective_pair_stop(tmp_path: Path) -> None:
    app = create_app(database_path=tmp_path / "control.db", start_watchdog=False)
    with TestClient(app):
        calls: list[tuple[str, str]] = []
        original = app.state.adapter.execute

        async def execute(command):
            calls.append((command.robot_id, command.operation))
            return await original(command)

        app.state.adapter.execute = execute
        app.state.adapter.set_scenario(MockScenario.FOLLOW_LOST)
        asyncio.run(app.state.runtime_tick())
        asyncio.run(app.state.runtime_tick())
        assert calls == [("robot_1", "stop"), ("robot_2", "stop")]
        assert any(alert.code == "FOLLOW_LOST" for alert in app.state.alert_service.list(state="ACTIVE"))


def test_active_formation_stops_once_for_communication_loss_or_stale(tmp_path: Path) -> None:
    for connection, expected in ((Connection.OFFLINE, "COMMUNICATION_LOSS"), (Connection.STALE, "COMMUNICATION_STALE")):
        app = create_app(database_path=tmp_path / f"{connection.value}.db", start_watchdog=False)
        with TestClient(app):
            source = app.state.adapter.snapshot()
            robots = [source.robots[0], source.robots[1].model_copy(update={"connection": connection})]
            app.state.state_store.snapshot_source = lambda source=source, robots=robots: source.model_copy(update={"robots": robots})
            app.state.state_store.formation_override = source.formation.model_copy(update={"state": FormationMode.FOLLOWING})
            calls: list[tuple[str, str]] = []
            original = app.state.adapter.execute

            async def execute(command):
                calls.append((command.robot_id, command.operation))
                return await original(command)

            app.state.adapter.execute = execute
            asyncio.run(app.state.runtime_tick())
            asyncio.run(app.state.runtime_tick())
            assert calls == [("robot_1", "stop"), ("robot_2", "stop")]
            assert any(alert.code == expected for alert in app.state.alert_service.list(state="ACTIVE"))


def test_follow_lost_keeps_lost_after_stop_confirmation_and_reactivation_clears_ack(tmp_path: Path) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    storage = Storage(tmp_path / "control.db", clock=lambda: now)
    service = AlertService(storage, clock=lambda: now)
    adapter = MockRobotAdapter()
    lost = snapshot_with(adapter, formation=FormationMode.LOST)
    follow = next(alert for alert in service.evaluate(lost) if alert.code == "FOLLOW_LOST")
    service.acknowledge(str(follow.alert_id), "operator")
    service.evaluate(snapshot_with(adapter))
    now += timedelta(seconds=3)
    service.evaluate(snapshot_with(adapter))
    assert service.get(str(follow.alert_id)).state == "RESOLVED"
    reactivated = next(alert for alert in service.evaluate(lost) if alert.code == "FOLLOW_LOST")
    assert reactivated.acknowledged_at is None and reactivated.acknowledged_by is None
    storage.close()

    app = create_app(database_path=tmp_path / "runtime.db", start_watchdog=False)
    with TestClient(app):
        source = app.state.adapter.snapshot()
        stopped = [robot.model_copy(update={"stop_latched": True, "linear_mps": 0.0, "angular_rps": 0.0}) for robot in source.robots]
        app.state.state_store.snapshot_source = lambda: source.model_copy(update={"robots": stopped, "formation": source.formation.model_copy(update={"state": FormationMode.LOST})})
        asyncio.run(app.state.runtime_tick())
        asyncio.run(app.state.runtime_tick())
        assert app.state.mission_service.formation().state == FormationMode.LOST


def test_rejected_protective_stop_becomes_explicit_unconfirmed_alert(tmp_path: Path) -> None:
    app = create_app(database_path=tmp_path / "control.db", start_watchdog=False)
    with TestClient(app):
        source = app.state.adapter.snapshot()
        app.state.state_store.snapshot_source = lambda: source.model_copy(update={"formation": source.formation.model_copy(update={"state": FormationMode.LOST})})
        calls: list[str] = []

        async def reject_stop(command):
            calls.append(command.robot_id)
            return CommandAcceptance(accepted=command.robot_id != "robot_2", reason_code="STOP_REJECTED")

        app.state.adapter.execute = reject_stop
        asyncio.run(app.state.runtime_tick())
        assert calls == ["robot_1", "robot_2"]
        assert app.state.mission_service.formation_pause_pending is None
        assert app.state.mission_service.formation().state == FormationMode.ERROR
        assert app.state.mission_service.formation().reason_code == "STOP_UNCONFIRMED"
        assert any(alert.code == "PROTECTIVE_STOP_UNCONFIRMED" for alert in app.state.alert_service.list(state="ACTIVE"))


def test_follow_lost_upgrades_an_existing_manual_pause_without_resending_stop(tmp_path: Path) -> None:
    app = create_app(database_path=tmp_path / "control.db", start_watchdog=False)
    with TestClient(app):
        source = app.state.adapter.snapshot()
        stopped = [robot.model_copy(update={"stop_latched": True, "linear_mps": 0.0, "angular_rps": 0.0}) for robot in source.robots]
        app.state.state_store.snapshot_source = lambda: source.model_copy(update={"robots": stopped, "formation": source.formation.model_copy(update={"state": FormationMode.LOST})})
        app.state.state_store.formation_override = source.formation.model_copy(update={"state": FormationMode.PAUSING, "reason_code": "FORMATION_PAUSE"})
        app.state.mission_service.formation_pause_pending = ("robot_1", "robot_2")
        app.state.mission_service.formation_pause_reason = "FORMATION_PAUSE"
        calls: list[str] = []

        async def execute(command):
            calls.append(command.robot_id)
            return CommandAcceptance(accepted=True)

        app.state.adapter.execute = execute
        asyncio.run(app.state.runtime_tick())
        assert calls == []
        assert app.state.mission_service.formation().state == FormationMode.LOST
        assert app.state.mission_service.formation().reason_code == "FOLLOW_LOST"
