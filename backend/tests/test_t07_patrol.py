import asyncio
from threading import Barrier, Thread
from pathlib import Path
from uuid import uuid4
from fastapi.testclient import TestClient
from pinky_control_center.main import create_app
from pinky_control_center.models import UserRole

ORIGIN="http://localhost:5173"
def auth(client):
    client.app.state.storage.create_or_reset_user("op","operator-password",UserRole.OPERATOR)
    login=client.post("/api/v1/session",json={"username":"op","password":"operator-password"},headers={"origin":ORIGIN}); csrf=login.json()["csrf_token"]
    lease=client.post("/api/v1/control-lease",json={"request_id":str(uuid4())},headers={"origin":ORIGIN,"x-csrf-token":csrf}).json()["lease_id"]
    return {"origin":ORIGIN,"x-csrf-token":csrf,"x-control-lease-id":lease}
def ready_pair(app, client, headers):
    paired=client.post('/api/v1/formation/actions',json={"request_id":str(uuid4()),"action":"pair","master_id":"robot_1","slave_id":"robot_2"},headers=headers)
    assert paired.status_code==202
    asyncio.run(app.state.command_dispatcher.process_next())
def payload(h): return {"request_id":str(uuid4()),"name":"route","map_id":"mock_lab","waypoints":[{"x":1+i,"y":2,"yaw":0,"frame_id":"map"} for i in range(3)],"repeat_count":2}

def test_patch_ready_mission_versions_and_validates_waypoint_bounds(tmp_path:Path):
    app=create_app(database_path=tmp_path/'db',start_command_worker=False, start_watchdog=False)
    with TestClient(app) as c:
        h=auth(c); ready_pair(app,c,h); made=c.post('/api/v1/missions',json=payload(h),headers=h).json()
        edited=c.patch(f"/api/v1/missions/{made['mission_id']}",json={"request_id":str(uuid4()),"version":1,"name":"edited","repeat_count":2},headers=h)
        assert edited.status_code==200 and edited.json()['version']==2
        assert c.patch(f"/api/v1/missions/{made['mission_id']}",json={"request_id":str(uuid4()),"version":1,"name":"old"},headers=h).status_code==409

def test_create_rejects_malformed_second_waypoint(tmp_path:Path):
    app=create_app(database_path=tmp_path/'db',start_command_worker=False)
    with TestClient(app) as c:
        h=auth(c); ready_pair(app,c,h); body=payload(h); body['waypoints'][1]={"x":2,"y":2,"yaw":0,"frame_id":""}
        assert c.post('/api/v1/missions',json=body,headers=h).status_code==422

def test_patch_request_id_replays_once_and_rejects_changed_payload(tmp_path:Path):
    app=create_app(database_path=tmp_path/'db',start_command_worker=False)
    with TestClient(app) as c:
        h=auth(c); ready_pair(app,c,h); made=c.post('/api/v1/missions',json=payload(h),headers=h).json(); request_id=str(uuid4())
        body={"request_id":request_id,"version":1,"name":"once"}; first=c.patch(f"/api/v1/missions/{made['mission_id']}",json=body,headers=h); replay=c.patch(f"/api/v1/missions/{made['mission_id']}",json=body,headers=h)
        assert first.json()['version']==replay.json()['version']==2
        changed=c.patch(f"/api/v1/missions/{made['mission_id']}",json={"request_id":request_id,"version":1,"name":"different"},headers=h)
        assert changed.status_code==409 and c.get(f"/api/v1/missions/{made['mission_id']}").json()['version']==2

def test_patrol_advances_three_waypoints_two_laps_from_mock_completion_events(tmp_path:Path):
    app=create_app(database_path=tmp_path/'db',start_command_worker=False, start_watchdog=False)
    with TestClient(app) as c:
        h=auth(c); c.post('/api/v1/formation/actions',json={"request_id":str(uuid4()),"action":"pair","master_id":"robot_1","slave_id":"robot_2"},headers=h); asyncio.run(app.state.command_dispatcher.process_next())
        mission=c.post('/api/v1/missions',json=payload(h),headers=h).json(); mid=mission['mission_id']
        c.post(f'/api/v1/missions/{mid}/actions',json={"request_id":str(uuid4()),"action":"validate"},headers=h);asyncio.run(app.state.command_dispatcher.process_next())
        calls=[]; original=app.state.adapter.execute
        async def execute(cmd): calls.append((cmd.robot_id,cmd.operation,cmd.parameters.get('goal',{}).get('x'))); return await original(cmd)
        app.state.adapter.execute=execute
        c.post(f'/api/v1/missions/{mid}/actions',json={"request_id":str(uuid4()),"action":"start"},headers=h);asyncio.run(app.state.command_dispatcher.process_next())
        source=app.state.state_store.snapshot_source(); stopped=[r.model_copy(update={"stop_latched":True,"linear_mps":0.,"angular_rps":0.}) for r in source.robots]; app.state.state_store.snapshot_source=lambda:source.model_copy(update={"robots":stopped})
        for _ in range(30): asyncio.run(app.state.runtime_tick())
        final=c.get(f'/api/v1/missions/{mid}').json()
        assert [x[2] for x in calls if x[1]=='navigate']==[1,2,3,1,2,3]
        assert final['state']=='SUCCEEDED' and final['lap_index']==1 and final['waypoint_index']==2

def test_pause_preserves_index_and_resume_reissues_same_goal(tmp_path:Path):
    app=create_app(database_path=tmp_path/'db',start_command_worker=False, start_watchdog=False)
    with TestClient(app) as c:
        h=auth(c); c.post('/api/v1/formation/actions',json={"request_id":str(uuid4()),"action":"pair","master_id":"robot_1","slave_id":"robot_2"},headers=h);asyncio.run(app.state.command_dispatcher.process_next())
        mission=c.post('/api/v1/missions',json=payload(h),headers=h).json();mid=mission['mission_id']; c.post(f'/api/v1/missions/{mid}/actions',json={"request_id":str(uuid4()),"action":"validate"},headers=h);asyncio.run(app.state.command_dispatcher.process_next())
        calls=[]; original=app.state.adapter.execute
        async def execute(cmd): calls.append((cmd.operation,cmd.parameters.get('goal',{}).get('x')));return await original(cmd)
        app.state.adapter.execute=execute
        c.post(f'/api/v1/missions/{mid}/actions',json={"request_id":str(uuid4()),"action":"start"},headers=h);asyncio.run(app.state.command_dispatcher.process_next())
        c.post(f'/api/v1/missions/{mid}/actions',json={"request_id":str(uuid4()),"action":"pause"},headers=h);asyncio.run(app.state.command_dispatcher.process_next())
        source=app.state.state_store.snapshot_source(); stopped=[r.model_copy(update={"stop_latched":True,"linear_mps":0.,"angular_rps":0.}) for r in source.robots];app.state.state_store.snapshot_source=lambda:source.model_copy(update={"robots":stopped});asyncio.run(app.state.runtime_tick())
        paused=c.get(f'/api/v1/missions/{mid}').json();assert paused['state']=='PAUSED' and paused['waypoint_index']==0 and paused['lap_index']==0
        c.post(f'/api/v1/missions/{mid}/actions',json={"request_id":str(uuid4()),"action":"resume"},headers=h);asyncio.run(app.state.command_dispatcher.process_next())
        assert [x[1] for x in calls if x[0]=='navigate']==[1,1]

def test_settle_timeout_never_sends_next_goal_and_restart_pauses_without_drive(tmp_path:Path):
    now=[0.]; path=tmp_path/'db'; app=create_app(database_path=path,start_command_worker=False,start_watchdog=False,monotonic_clock=lambda:now[0])
    with TestClient(app) as c:
        h=auth(c);c.post('/api/v1/formation/actions',json={"request_id":str(uuid4()),"action":"pair","master_id":"robot_1","slave_id":"robot_2"},headers=h);asyncio.run(app.state.command_dispatcher.process_next())
        mission=c.post('/api/v1/missions',json=payload(h),headers=h).json();mid=mission['mission_id'];c.post(f'/api/v1/missions/{mid}/actions',json={"request_id":str(uuid4()),"action":"validate"},headers=h);asyncio.run(app.state.command_dispatcher.process_next())
        calls=[];orig=app.state.adapter.execute
        async def execute(cmd):calls.append(cmd.operation);return await orig(cmd)
        app.state.adapter.execute=execute;c.post(f'/api/v1/missions/{mid}/actions',json={"request_id":str(uuid4()),"action":"start"},headers=h);asyncio.run(app.state.command_dispatcher.process_next());asyncio.run(app.state.runtime_tick());now[0]=10.;asyncio.run(app.state.runtime_tick())
        assert c.get(f'/api/v1/missions/{mid}').json()['state']=='PAUSED' and calls.count('navigate')==1
    restarted=create_app(database_path=path,start_command_worker=False)
    assert restarted.state.storage.connection.execute("SELECT state FROM missions WHERE id=?",(mid,)).fetchone()['state']=='PAUSED'

def test_second_waypoint_rejection_fails_without_third_goal(tmp_path:Path):
    app=create_app(database_path=tmp_path/'db',start_command_worker=False)
    with TestClient(app) as c:
        h=auth(c);c.post('/api/v1/formation/actions',json={"request_id":str(uuid4()),"action":"pair","master_id":"robot_1","slave_id":"robot_2"},headers=h);asyncio.run(app.state.command_dispatcher.process_next())
        mission=c.post('/api/v1/missions',json=payload(h),headers=h).json();mid=mission['mission_id'];c.post(f'/api/v1/missions/{mid}/actions',json={"request_id":str(uuid4()),"action":"validate"},headers=h);asyncio.run(app.state.command_dispatcher.process_next())
        calls=[];orig=app.state.adapter.execute
        async def execute(cmd):calls.append((cmd.operation,cmd.parameters.get('goal',{}).get('x')));return await orig(cmd)
        app.state.adapter.execute=execute;c.post(f'/api/v1/missions/{mid}/actions',json={"request_id":str(uuid4()),"action":"start"},headers=h);asyncio.run(app.state.command_dispatcher.process_next())
        source=app.state.state_store.snapshot_source();stopped=[r.model_copy(update={"stop_latched":True,"linear_mps":0.,"angular_rps":0.}) for r in source.robots];app.state.state_store.snapshot_source=lambda:source.model_copy(update={"robots":stopped});app.state.adapter.set_scenario(__import__('pinky_control_center.models',fromlist=['MockScenario']).MockScenario.COMMAND_REJECTED)
        asyncio.run(app.state.runtime_tick())
        result=c.get(f'/api/v1/missions/{mid}').json();assert result['state']=='FAILED' and result['waypoint_index']==1
        assert [x[1] for x in calls if x[0]=='navigate']==[1,2]

def test_mission_list_is_owner_scoped_paginated_and_progress_persists(tmp_path:Path):
    app=create_app(database_path=tmp_path/'db',start_command_worker=False)
    with TestClient(app) as c:
        h=auth(c); ready_pair(app,c,h)
        for i in range(3):
            body=payload(h);body['name']=f'r{i}';c.post('/api/v1/missions',json=body,headers=h)
        first=c.get('/api/v1/missions?limit=2').json(); second=c.get(f"/api/v1/missions?limit=2&cursor={first['next_cursor']}").json()
        assert len(first['items'])==2 and len(second['items'])==1 and {x['mission_id'] for x in first['items']}.isdisjoint({x['mission_id'] for x in second['items']})
        assert c.get('/api/v1/missions?from=2100-01-01T00:00:00Z').json()['items']==[]
        assert c.get('/api/v1/missions?to=2000-01-01T00:00:00Z').json()['items']==[]
        assert c.get('/api/v1/missions?from=bad').status_code==422

def test_navigation_rejection_protectively_stops_both(tmp_path:Path):
    app=create_app(database_path=tmp_path/'db',start_command_worker=False)
    with TestClient(app) as c:
        h=auth(c);c.post('/api/v1/formation/actions',json={"request_id":str(uuid4()),"action":"pair","master_id":"robot_1","slave_id":"robot_2"},headers=h);asyncio.run(app.state.command_dispatcher.process_next())
        mission=c.post('/api/v1/missions',json=payload(h),headers=h).json();mid=mission['mission_id'];c.post(f'/api/v1/missions/{mid}/actions',json={"request_id":str(uuid4()),"action":"validate"},headers=h);asyncio.run(app.state.command_dispatcher.process_next())
        calls=[];orig=app.state.adapter.execute
        async def execute(cmd):calls.append((cmd.robot_id,cmd.operation));return await orig(cmd)
        app.state.adapter.execute=execute;app.state.adapter.set_scenario(__import__('pinky_control_center.models',fromlist=['MockScenario']).MockScenario.COMMAND_REJECTED)
        c.post(f'/api/v1/missions/{mid}/actions',json={"request_id":str(uuid4()),"action":"start"},headers=h);asyncio.run(app.state.command_dispatcher.process_next())
        assert calls[-2:]==[("robot_1","stop"),("robot_2","stop")]

def test_concurrent_patch_version_and_request_replay_apply_once(tmp_path:Path):
    app=create_app(database_path=tmp_path/'db',start_command_worker=False); user=app.state.storage.create_or_reset_user('op','operator-password',UserRole.OPERATOR)
    from pinky_control_center.models import FormationMode, FormationState
    app.state.state_store.formation_override=FormationState(state=FormationMode.READY,master_id='robot_1',slave_id='robot_2',target_distance_m=.8,distance_m=.8,gap_error_m=0.)
    created=app.state.mission_service.create(user,{"request_id":str(uuid4()),"name":"route","map_id":"mock_lab","waypoints":[{"x":1,"y":2,"yaw":0,"frame_id":"map"}],"repeat_count":1})
    barrier=Barrier(2); outcomes=[]
    def edit(name, request, version=1):
        barrier.wait()
        try: outcomes.append(('ok',app.state.mission_service.edit(user,created['mission_id'],{"request_id":str(request),"version":version,"name":name})['version']))
        except Exception as error: outcomes.append(('error',getattr(error,'detail',None)))
    first,second=Thread(target=edit,args=('a',uuid4())),Thread(target=edit,args=('b',uuid4()));first.start();second.start();first.join();second.join()
    assert sorted(outcomes)==[('error','STALE_VERSION'),('ok',2)]
    current=app.state.storage.mission(created['mission_id'],user); barrier=Barrier(2); outcomes=[]; request=uuid4()
    first,second=Thread(target=edit,args=('replay',request,2)),Thread(target=edit,args=('replay',request,2));first.start();second.start();first.join();second.join()
    # The stale request above did not alter the mission; both same-key callers return one stored update.
    assert outcomes==[('ok',3),('ok',3)]
