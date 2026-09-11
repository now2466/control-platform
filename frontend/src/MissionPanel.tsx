import { useEffect, useState } from 'react'
import { createMission, getMission, listMissions, missionAction, updateMission, waitForCommand } from './api'
import type { Goal, Mission } from './api'

type Props = { lease: string | null; mapId?: string | null; formation?: { state?: string }; goal: Goal | null; onError: (message: string) => void }
const editableStates = new Set(['DRAFT', 'READY'])

export default function MissionPanel({ lease, mapId, formation, goal, onError }: Props) {
  const [mission, setMission] = useState<Mission | null>(null)
  const [points, setPoints] = useState<Goal[]>(goal ? [goal] : [])
  const [name, setName] = useState('단일 목표 임무')
  const [repeat, setRepeat] = useState(1)
  const [busy, setBusy] = useState(false)
  const [savedMissions, setSavedMissions] = useState<Mission[]>([])
  const state = mission?.state ?? 'DRAFT'
  const usable = Boolean(lease && mapId && points.length && formation?.state === 'READY')
  const resumable = Boolean(lease && mapId && points.length && state === 'PAUSED' && ['READY', 'PAUSED'].includes(formation?.state ?? ''))
  const editable = !mission || editableStates.has(state)
  const cancellable = ['DRAFT', 'READY', 'RUNNING', 'PAUSED'].includes(state)
  const validName = name.trim().length > 0 && name.trim().length <= 100
  const validPoints = points.length >= 1 && points.length <= 100

  const refreshMissions = () => { listMissions().then(setSavedMissions).catch(error => onError((error as Error).message)) }

  useEffect(() => {
    if (!goal) return
    setPoints(current => current.length >= 100 || current.some(p => p.x === goal.x && p.y === goal.y && p.yaw === goal.yaw) ? current : [...current, goal])
  }, [goal?.x, goal?.y, goal?.yaw, goal?.frame_id])

  const runAction = async (action: 'validate' | 'start' | 'pause' | 'resume' | 'cancel') => {
    if (!mission || !lease || busy) return
    setBusy(true)
    let command: { command_id?: string } | undefined
    try { const issued = await missionAction(mission.mission_id, action, lease); command = issued; await waitForCommand(String(issued.command_id)); setMission(await getMission(mission.mission_id)) }
    catch (error) {
      onError((error as Error).message)
      if (command?.command_id) { try { setMission(await getMission(mission.mission_id)) } catch { /* preserve command error */ } }
    } finally { setBusy(false) }
  }
  const create = async () => {
    if (!usable || !mapId || busy || !validName || !validPoints) return
    setBusy(true)
    try { setMission(await createMission(points, mapId, lease!, name, repeat)) }
    catch (error) { onError((error as Error).message) } finally { setBusy(false) }
  }
  const save = async () => {
    if (!mission || !lease || !editable || busy || !validName || !validPoints) return
    setBusy(true)
    try { setMission(await updateMission(mission.mission_id, points, name, repeat, mission.version ?? 1, lease)) }
    catch (error) { onError((error as Error).message) } finally { setBusy(false) }
  }

  return <section className="mission-panel">
    <h2>임무 · {state}</h2>
    <button onClick={refreshMissions}>임무 목록 새로고침</button><label>임무 불러오기<select aria-label="저장된 임무" value={mission?.mission_id ?? ''} onChange={event => { const selected = savedMissions.find(item => item.mission_id === event.target.value); if (selected) { setMission(selected); setPoints(selected.waypoints ?? []); setName(selected.name ?? '임무'); setRepeat(selected.repeat_count ?? 1) } }}><option value="">새 임무</option>{savedMissions.map(item => <option key={item.mission_id} value={item.mission_id}>{item.name ?? item.mission_id} · {item.state}</option>)}</select></label>
    <label>이름<input disabled={!editable || busy} maxLength={100} value={name} onChange={event => setName(event.target.value)} /></label>
    <label>반복 <input disabled={!editable || busy} aria-label="반복" type="number" min="1" max="100" value={repeat} onChange={event => setRepeat(Math.max(1, Math.min(100, Number(event.target.value) || 1)))} /></label>
    <p data-testid="mission-progress">waypoint {points.length}개 · 현재 {(mission?.waypoint_index ?? 0) + 1}/{mission?.waypoints?.length ?? points.length} · lap {(mission?.lap_index ?? 0) + 1}/{mission?.repeat_count ?? repeat} · 진행 {mission?.progress_distance_m == null ? '—' : `${mission.progress_distance_m}m`}</p>
    {mission?.failure_code && <strong role="alert">오류: {mission.failure_code}</strong>}
    <ol>{points.map((point, index) => <li key={`${point.x}-${point.y}-${index}`}>{point.x.toFixed(2)}, {point.y.toFixed(2)} <button disabled={!editable || busy} onClick={() => setPoints(value => value.filter((_, i) => i !== index))}>삭제</button><button disabled={!editable || busy || index === 0} onClick={() => setPoints(value => { const next = [...value]; [next[index - 1], next[index]] = [next[index], next[index - 1]]; return next })}>위</button><button disabled={!editable || busy || index === points.length - 1} onClick={() => setPoints(value => { const next = [...value]; [next[index + 1], next[index]] = [next[index], next[index + 1]]; return next })}>아래</button></li>)}</ol>
    <button disabled={!usable || !validName || !validPoints || busy || Boolean(mission)} onClick={create}>임무 생성</button><button disabled={!mission || !editable || !validName || !validPoints || busy} onClick={save}>저장</button><button disabled={!mission || busy || state !== 'DRAFT'} onClick={() => runAction('validate')}>검증</button><button disabled={!mission || busy || state !== 'READY' || !usable} onClick={() => runAction('start')}>시작</button><button disabled={!mission || busy || state !== 'RUNNING'} onClick={() => runAction('pause')}>일시정지</button><button disabled={!resumable || busy} onClick={() => runAction('resume')}>재개</button><button disabled={!mission || busy || !cancellable} onClick={() => runAction('cancel')}>취소</button>
    {!usable && <p className="map-warning">READY 편대·lease·유효 waypoint가 필요합니다.</p>}
  </section>
}
