import asyncio
from threading import Barrier, Thread
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from pinky_control_center.main import create_app
from pinky_control_center.models import UserRole
from pinky_control_center.models import MockScenario

ORIGIN = "http://localhost:5173"


def headers(client):
    client.app.state.storage.create_or_reset_user("operator", "operator-password", UserRole.OPERATOR)
    login = client.post("/api/v1/session", json={"username": "operator", "password": "operator-password"}, headers={"origin": ORIGIN})
    csrf = login.json()["csrf_token"]
    lease = client.post("/api/v1/control-lease", json={"request_id": str(uuid4())}, headers={"origin": ORIGIN, "x-csrf-token": csrf}).json()["lease_id"]
    return {"origin": ORIGIN, "x-csrf-token": csrf, "x-control-lease-id": lease}


def test_pair_requires_ready_robots_and_transitions_to_ready(tmp_path: Path):
    app = create_app(database_path=tmp_path / "control.db", start_command_worker=False)
    with TestClient(app) as client:
        h = headers(client)
        pair = client.post("/api/v1/formation/actions", json={"request_id": str(uuid4()), "action": "pair", "master_id": "robot_1", "slave_id": "robot_2"}, headers=h)
        assert pair.status_code == 202
        asyncio.run(app.state.command_dispatcher.process_next())
        assert client.get("/api/v1/state").json()["formation"]["state"] == "READY"


def test_mission_start_sends_slave_ready_and_follow_before_master_navigation(tmp_path: Path):
    app = create_app(database_path=tmp_path / "control.db", start_command_worker=False)
    with TestClient(app) as client:
        h = headers(client)
        pair = client.post("/api/v1/formation/actions", json={"request_id": str(uuid4()), "action": "pair", "master_id": "robot_1", "slave_id": "robot_2"}, headers=h)
        asyncio.run(app.state.command_dispatcher.process_next())
        made = client.post("/api/v1/missions", json={"request_id": str(uuid4()), "name": "one", "map_id": "mock_lab", "waypoints": [{"x": 2, "y": 2, "yaw": 0, "frame_id": "map"}], "repeat_count": 1}, headers=h)
        assert made.status_code == 201
        mission = made.json()
        assert client.post(f"/api/v1/missions/{mission['mission_id']}/actions", json={"request_id": str(uuid4()), "action": "validate"}, headers=h).status_code == 202
        asyncio.run(app.state.command_dispatcher.process_next())
        calls=[]; original=app.state.adapter.execute
        async def execute(command): calls.append((command.robot_id, command.operation)); return await original(command)
        app.state.adapter.execute=execute
        started=client.post(f"/api/v1/missions/{mission['mission_id']}/actions", json={"request_id": str(uuid4()), "action": "start"}, headers=h)
        assert started.status_code == 202
        asyncio.run(app.state.command_dispatcher.process_next())
        assert calls == [("robot_2", "follow_ready"), ("robot_2", "follow_start"), ("robot_1", "navigate")]
        assert client.get(f"/api/v1/missions/{mission['mission_id']}").json()["state"] == "RUNNING"


def test_pause_is_transitional_until_both_stop_observations_confirm(tmp_path: Path):
    app = create_app(database_path=tmp_path / "control.db", start_command_worker=False)
    with TestClient(app) as client:
        h = headers(client)
        service = app.state.mission_service
        mission = app.state.storage.create_mission(client.app.state.storage.authenticate("operator", "operator-password"), {"name":"one", "state":"RUNNING", "master_id":"robot_1", "slave_id":"robot_2", "map_id":"mock_lab", "waypoints":[{"x":2,"y":2,"yaw":0,"frame_id":"map"}], "repeat_count":1,"waypoint_index":0,"lap_index":0,"progress_distance_m":None,"failure_code":None})
        service.active_id = mission["mission_id"]
        service._set_formation(__import__('pinky_control_center.models', fromlist=['FormationMode']).FormationMode.FOLLOWING)
        paused = client.post(f"/api/v1/missions/{mission['mission_id']}/actions", json={"request_id":str(uuid4()),"action":"pause"}, headers=h)
        assert paused.status_code == 202
        asyncio.run(app.state.command_dispatcher.process_next())
        assert client.get(f"/api/v1/missions/{mission['mission_id']}").json()["state"] == "PAUSING"
        source = app.state.state_store.snapshot_source()
        stopped = [robot.model_copy(update={"stop_latched":True,"linear_mps":0.,"angular_rps":0.}) for robot in source.robots]
        app.state.state_store.snapshot_source = lambda: source.model_copy(update={"robots":stopped})
        asyncio.run(app.state.runtime_tick())
        assert client.get(f"/api/v1/missions/{mission['mission_id']}").json()["state"] == "PAUSED"


def test_master_success_without_slave_settle_pauses_after_ten_fake_seconds(tmp_path: Path):
    now = [0.0]
    app = create_app(database_path=tmp_path / "control.db", start_command_worker=False, monotonic_clock=lambda: now[0])
    with TestClient(app):
        user = app.state.storage.create_or_reset_user("operator", "operator-password", UserRole.OPERATOR)
        mission = app.state.storage.create_mission(user, {"name":"one", "state":"RUNNING", "master_id":"robot_1", "slave_id":"robot_2", "map_id":"mock_lab", "waypoints":[{"x":2,"y":2,"yaw":0,"frame_id":"map"}], "repeat_count":1,"waypoint_index":0,"lap_index":0,"progress_distance_m":None,"failure_code":None})
        app.state.mission_service.active_id = mission["mission_id"]
        app.state.mission_service._set_formation(__import__('pinky_control_center.models', fromlist=['FormationMode']).FormationMode.FOLLOWING)
        app.state.mission_service.master_navigation_succeeded(mission["mission_id"])
        now[0] = 9.99; asyncio.run(app.state.runtime_tick())
        assert app.state.storage.mission(mission["mission_id"], user)["state"] == "RUNNING"
        now[0] = 10.; asyncio.run(app.state.runtime_tick())
        assert app.state.storage.mission(mission["mission_id"], user)["state"] == "PAUSED"


def test_invalid_transition_and_offline_pair_are_409(tmp_path: Path):
    app=create_app(database_path=tmp_path/"control.db", start_command_worker=False)
    with TestClient(app) as client:
        h=headers(client)
        assert client.post("/api/v1/formation/actions",json={"request_id":str(uuid4()),"action":"pause","master_id":"robot_1","slave_id":"robot_2"},headers=h).status_code==409
        app.state.adapter.set_scenario(MockScenario.SLAVE_OFFLINE)
        assert client.post("/api/v1/formation/actions",json={"request_id":str(uuid4()),"action":"pair","master_id":"robot_1","slave_id":"robot_2"},headers=h).status_code==409


def test_slave_rejection_never_navigates_master_and_stops_both(tmp_path: Path):
    app=create_app(database_path=tmp_path/"control.db", start_command_worker=False)
    with TestClient(app) as client:
        h=headers(client)
        pair=client.post("/api/v1/formation/actions",json={"request_id":str(uuid4()),"action":"pair","master_id":"robot_1","slave_id":"robot_2"},headers=h); asyncio.run(app.state.command_dispatcher.process_next())
        mission=client.post("/api/v1/missions",json={"request_id":str(uuid4()),"name":"one","map_id":"mock_lab","waypoints":[{"x":2,"y":2,"yaw":0,"frame_id":"map"}],"repeat_count":1},headers=h).json()
        client.post(f"/api/v1/missions/{mission['mission_id']}/actions",json={"request_id":str(uuid4()),"action":"validate"},headers=h); asyncio.run(app.state.command_dispatcher.process_next())
        app.state.adapter.set_scenario(MockScenario.COMMAND_REJECTED); calls=[]; original=app.state.adapter.execute
        async def execute(command): calls.append((command.robot_id,command.operation)); return await original(command)
        app.state.adapter.execute=execute
        start=client.post(f"/api/v1/missions/{mission['mission_id']}/actions",json={"request_id":str(uuid4()),"action":"start"},headers=h).json(); asyncio.run(app.state.command_dispatcher.process_next())
        assert ("robot_1","navigate") not in calls
        assert calls[-2:]==[("robot_1","stop"),("robot_2","stop")]
        assert client.get(f"/api/v1/commands/{start['command_id']}").json()["state"]=="FAILED"


def test_mission_mutations_need_owned_lease_and_create_replays_same_request(tmp_path: Path):
    app=create_app(database_path=tmp_path/"control.db", start_command_worker=False)
    with TestClient(app) as client:
        h=headers(client); body={"request_id":str(uuid4()),"name":"one","map_id":"mock_lab","waypoints":[{"x":2,"y":2,"yaw":0,"frame_id":"map"}],"repeat_count":1}
        no_lease={key:value for key,value in h.items() if key != "x-control-lease-id"}
        assert client.post("/api/v1/missions",json=body,headers=no_lease).status_code==409
        first=client.post("/api/v1/missions",json=body,headers=h)
        same=client.post("/api/v1/missions",json=body,headers=h)
        assert first.status_code==same.status_code==201
        assert first.json()["mission_id"]==same.json()["mission_id"]


def test_mock_navigation_completion_event_starts_slave_wait_deadline(tmp_path: Path):
    now=[0.0]; app=create_app(database_path=tmp_path/"control.db", start_command_worker=False,monotonic_clock=lambda:now[0])
    with TestClient(app) as client:
        h=headers(client)
        client.post("/api/v1/formation/actions",json={"request_id":str(uuid4()),"action":"pair","master_id":"robot_1","slave_id":"robot_2"},headers=h); asyncio.run(app.state.command_dispatcher.process_next())
        mission=client.post("/api/v1/missions",json={"request_id":str(uuid4()),"name":"one","map_id":"mock_lab","waypoints":[{"x":2,"y":2,"yaw":0,"frame_id":"map"}],"repeat_count":1},headers=h).json()
        client.post(f"/api/v1/missions/{mission['mission_id']}/actions",json={"request_id":str(uuid4()),"action":"validate"},headers=h); asyncio.run(app.state.command_dispatcher.process_next())
        client.post(f"/api/v1/missions/{mission['mission_id']}/actions",json={"request_id":str(uuid4()),"action":"start"},headers=h); asyncio.run(app.state.command_dispatcher.process_next())
        asyncio.run(app.state.runtime_tick())
        assert app.state.mission_service.slave_wait_deadline==10.0


def test_cancel_persists_canceled_after_stop_confirmation(tmp_path: Path):
    app=create_app(database_path=tmp_path/"control.db", start_command_worker=False)
    with TestClient(app) as client:
        h=headers(client); user=app.state.storage.authenticate("operator","operator-password")
        mission=app.state.storage.create_mission(user,{"name":"one","state":"RUNNING","master_id":"robot_1","slave_id":"robot_2","map_id":"mock_lab","waypoints":[{"x":2,"y":2,"yaw":0,"frame_id":"map"}],"repeat_count":1,"waypoint_index":0,"lap_index":0,"progress_distance_m":None,"failure_code":None})
        app.state.mission_service.active_id=mission["mission_id"]
        accepted=client.post(f"/api/v1/missions/{mission['mission_id']}/actions",json={"request_id":str(uuid4()),"action":"cancel"},headers=h)
        assert accepted.status_code==202; asyncio.run(app.state.command_dispatcher.process_next())
        assert app.state.storage.mission(mission["mission_id"],user)["state"]=="CANCELING"
        source=app.state.state_store.snapshot_source(); stopped=[robot.model_copy(update={"stop_latched":True,"linear_mps":0.,"angular_rps":0.}) for robot in source.robots]
        app.state.state_store.snapshot_source=lambda:source.model_copy(update={"robots":stopped})
        asyncio.run(app.state.runtime_tick())
        assert app.state.storage.mission(mission["mission_id"],user)["state"]=="CANCELED"
        assert app.state.mission_service.active_id is None


def test_cancel_stop_rejection_keeps_transitional_state_and_reason(tmp_path: Path):
    app=create_app(database_path=tmp_path/"control.db", start_command_worker=False)
    with TestClient(app) as client:
        h=headers(client); user=app.state.storage.authenticate("operator","operator-password")
        mission=app.state.storage.create_mission(user,{"name":"one","state":"RUNNING","master_id":"robot_1","slave_id":"robot_2","map_id":"mock_lab","waypoints":[{"x":2,"y":2,"yaw":0,"frame_id":"map"}],"repeat_count":1,"waypoint_index":0,"lap_index":0,"progress_distance_m":None,"failure_code":None})
        app.state.mission_service.active_id=mission["mission_id"]; app.state.adapter.set_scenario(MockScenario.COMMAND_REJECTED)
        command=client.post(f"/api/v1/missions/{mission['mission_id']}/actions",json={"request_id":str(uuid4()),"action":"cancel"},headers=h).json()
        asyncio.run(app.state.command_dispatcher.process_next())
        persisted=app.state.storage.mission(mission["mission_id"],user)
        assert persisted["state"]=="CANCELING" and persisted["failure_code"]=="STOP_UNCONFIRMED"
        assert client.get(f"/api/v1/commands/{command['command_id']}").json()["state"]=="FAILED"


def test_concurrent_mission_create_reuses_one_persisted_mission(tmp_path: Path):
    app=create_app(database_path=tmp_path/"control.db", start_command_worker=False); user=app.state.storage.create_or_reset_user("operator","operator-password",UserRole.OPERATOR)
    payload={"name":"one","state":"DRAFT","master_id":"robot_1","slave_id":"robot_2","map_id":"mock_lab","waypoints":[{"x":2,"y":2,"yaw":0,"frame_id":"map"}],"repeat_count":1,"waypoint_index":0,"lap_index":0,"progress_distance_m":None,"failure_code":None}; request_id=uuid4(); barrier=Barrier(2); results=[]
    def create(): barrier.wait(); results.append(app.state.storage.create_mission_idempotent(user,request_id,payload)["mission_id"])
    threads=[Thread(target=create),Thread(target=create)]
    for thread in threads: thread.start()
    for thread in threads: thread.join()
    assert len(set(results))==1
    assert app.state.storage.connection.execute("SELECT count(*) FROM missions").fetchone()[0]==1


def test_rejoin_requires_ready_pair_and_stops_both_before_ready(tmp_path: Path):
    app=create_app(database_path=tmp_path/"control.db", start_command_worker=False)
    with TestClient(app) as client:
        h=headers(client); from pinky_control_center.models import FormationMode
        app.state.mission_service._set_formation(FormationMode.LOST,"FOLLOW_LOST"); calls=[]; original=app.state.adapter.execute
        async def execute(command): calls.append((command.robot_id,command.operation)); return await original(command)
        app.state.adapter.execute=execute
        response=client.post("/api/v1/formation/actions",json={"request_id":str(uuid4()),"action":"rejoin","master_id":"robot_1","slave_id":"robot_2"},headers=h)
        assert response.status_code==202; asyncio.run(app.state.command_dispatcher.process_next())
        assert calls[:2]==[("robot_1","stop"),("robot_2","stop")]
        assert client.get("/api/v1/state").json()["formation"]["state"]=="READY"


def test_rejoin_failure_leaves_formation_error(tmp_path: Path):
    app=create_app(database_path=tmp_path/"control.db", start_command_worker=False)
    with TestClient(app) as client:
        h=headers(client); from pinky_control_center.models import FormationMode
        app.state.mission_service._set_formation(FormationMode.LOST,"FOLLOW_LOST"); app.state.adapter.set_scenario(MockScenario.COMMAND_REJECTED)
        command=client.post("/api/v1/formation/actions",json={"request_id":str(uuid4()),"action":"rejoin","master_id":"robot_1","slave_id":"robot_2"},headers=h).json()
        asyncio.run(app.state.command_dispatcher.process_next())
        assert client.get(f"/api/v1/commands/{command['command_id']}").json()["state"]=="FAILED"
        assert client.get("/api/v1/state").json()["formation"]["state"]=="ERROR"


def test_draft_cancel_completes_without_active_mission_tracking(tmp_path: Path):
    app=create_app(database_path=tmp_path/"control.db", start_command_worker=False)
    with TestClient(app) as client:
        h=headers(client)
        mission=client.post("/api/v1/missions",json={"request_id":str(uuid4()),"name":"draft","map_id":"mock_lab","waypoints":[{"x":2,"y":2,"yaw":0,"frame_id":"map"}],"repeat_count":1},headers=h).json()
        accepted=client.post(f"/api/v1/missions/{mission['mission_id']}/actions",json={"request_id":str(uuid4()),"action":"cancel"},headers=h)
        assert accepted.status_code==202; asyncio.run(app.state.command_dispatcher.process_next())
        assert client.get(f"/api/v1/missions/{mission['mission_id']}").json()["state"]=="CANCELED"


def test_formation_pause_waits_for_dual_stop_observation(tmp_path: Path):
    app=create_app(database_path=tmp_path/"control.db", start_command_worker=False)
    with TestClient(app) as client:
        h=headers(client); from pinky_control_center.models import FormationMode
        app.state.mission_service._set_formation(FormationMode.FOLLOWING); calls=[]; original=app.state.adapter.execute
        async def execute(command): calls.append((command.robot_id,command.operation)); return await original(command)
        app.state.adapter.execute=execute
        command=client.post("/api/v1/formation/actions",json={"request_id":str(uuid4()),"action":"pause","master_id":"robot_1","slave_id":"robot_2"},headers=h).json()
        asyncio.run(app.state.command_dispatcher.process_next())
        assert calls==[("robot_1","cancel_navigation"),("robot_1","stop"),("robot_2","stop")]
        assert client.get(f"/api/v1/commands/{command['command_id']}").json()["state"]=="SUCCEEDED"
        assert client.get("/api/v1/state").json()["formation"]["state"]=="PAUSING"
        source=app.state.state_store.snapshot_source(); stopped=[robot.model_copy(update={"stop_latched":True,"linear_mps":0.,"angular_rps":0.}) for robot in source.robots]
        app.state.state_store.snapshot_source=lambda:source.model_copy(update={"robots":stopped}); asyncio.run(app.state.runtime_tick())
        assert client.get("/api/v1/state").json()["formation"]["state"]=="PAUSED"


def test_formation_pause_rejection_marks_error_and_command_failed(tmp_path: Path):
    app=create_app(database_path=tmp_path/"control.db", start_command_worker=False)
    with TestClient(app) as client:
        h=headers(client); from pinky_control_center.models import FormationMode
        app.state.mission_service._set_formation(FormationMode.FOLLOWING); app.state.adapter.set_scenario(MockScenario.COMMAND_REJECTED)
        command=client.post("/api/v1/formation/actions",json={"request_id":str(uuid4()),"action":"pause","master_id":"robot_1","slave_id":"robot_2"},headers=h).json()
        asyncio.run(app.state.command_dispatcher.process_next())
        assert client.get(f"/api/v1/commands/{command['command_id']}").json()["state"]=="FAILED"
        formation=client.get("/api/v1/state").json()["formation"]
        assert formation["state"]=="ERROR" and formation["reason_code"]=="STOP_UNCONFIRMED"


def test_stale_zero_speed_does_not_complete_formation_pause(tmp_path: Path):
    app=create_app(database_path=tmp_path/"control.db", start_command_worker=False)
    with TestClient(app) as client:
        h=headers(client); from pinky_control_center.models import FormationMode, Freshness
        app.state.mission_service._set_formation(FormationMode.FOLLOWING)
        client.post("/api/v1/formation/actions",json={"request_id":str(uuid4()),"action":"pause","master_id":"robot_1","slave_id":"robot_2"},headers=h); asyncio.run(app.state.command_dispatcher.process_next())
        source=app.state.state_store.snapshot_source(); stale=[robot.model_copy(update={"stop_latched":True,"linear_mps":0.,"angular_rps":0.,"pose_freshness":Freshness.STALE}) for robot in source.robots]
        app.state.state_store.snapshot_source=lambda:source.model_copy(update={"robots":stale}); asyncio.run(app.state.runtime_tick())
        assert client.get("/api/v1/state").json()["formation"]["state"]=="PAUSING"


def test_stale_zero_speed_does_not_complete_mission_pause(tmp_path: Path):
    app=create_app(database_path=tmp_path/"control.db", start_command_worker=False)
    with TestClient(app) as client:
        h=headers(client); user=app.state.storage.authenticate("operator","operator-password")
        mission=app.state.storage.create_mission(user,{"name":"one","state":"RUNNING","master_id":"robot_1","slave_id":"robot_2","map_id":"mock_lab","waypoints":[{"x":2,"y":2,"yaw":0,"frame_id":"map"}],"repeat_count":1,"waypoint_index":0,"lap_index":0,"progress_distance_m":None,"failure_code":None}); app.state.mission_service.active_id=mission["mission_id"]
        client.post(f"/api/v1/missions/{mission['mission_id']}/actions",json={"request_id":str(uuid4()),"action":"pause"},headers=h); asyncio.run(app.state.command_dispatcher.process_next())
        source=app.state.state_store.snapshot_source(); from pinky_control_center.models import Freshness
        stale=[robot.model_copy(update={"stop_latched":True,"linear_mps":0.,"angular_rps":0.,"pose_freshness":Freshness.STALE}) for robot in source.robots]
        app.state.state_store.snapshot_source=lambda:source.model_copy(update={"robots":stale}); asyncio.run(app.state.runtime_tick())
        assert app.state.storage.mission(mission["mission_id"],user)["state"]=="PAUSING"
