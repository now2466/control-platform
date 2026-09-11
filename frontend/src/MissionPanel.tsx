import { useEffect, useState } from 'react'
import { createMission, getMission, missionAction, waitForCommand } from './api'
import type { Goal, Mission } from './api'

export default function MissionPanel({ lease, mapId, formation, goal, onError }: { lease: string | null; mapId?: string | null; formation?: { state?: string }; goal: Goal | null; onError: (message: string) => void }) {
  const [mission, setMission] = useState<Mission | null>(null)
  const [busy, setBusy] = useState(false)
  const usable = Boolean(lease && mapId && goal && formation?.state === 'READY')
  const state = mission?.state ?? 'DRAFT'

  useEffect(() => setMission(null), [goal?.x, goal?.y, goal?.yaw, mapId])
  const refresh = async (missionId: string) => {
    try { setMission(await getMission(missionId)) } catch (error) { onError((error as Error).message) }
  }
  const create = async () => {
    if (!goal || !mapId || !lease) return
    setBusy(true)
    try { setMission(await createMission(goal, mapId, lease)) } catch (error) { onError((error as Error).message) } finally { setBusy(false) }
  }
  const action = async (next: 'validate' | 'start' | 'pause' | 'resume' | 'cancel') => {
    if (!mission || !lease) return
    setBusy(true)
    try {
      const command = await missionAction(mission.mission_id, next, lease)
      await waitForCommand(String(command.command_id))
      await refresh(mission.mission_id)
    } catch (error) { onError((error as Error).message) } finally { setBusy(false) }
  }

  return <section className="mission-panel">
    <h2>단일 목표 임무 · {state}</h2>
    <p>목표: {goal ? `${goal.x.toFixed(2)}, ${goal.y.toFixed(2)} (${goal.frame_id})` : '지도에서 목표를 지정하세요.'}</p>
    {mission?.progress_distance_m != null && <p>남은 거리: {mission.progress_distance_m.toFixed(2)}m</p>}
    {mission?.failure_code && <strong>{mission.failure_code}</strong>}
    <div>
      <button disabled={busy || !usable} onClick={create}>임무 생성</button>
      <button disabled={busy || !mission || state !== 'DRAFT'} onClick={() => action('validate')}>검증</button>
      <button disabled={busy || !mission || state !== 'READY' || !usable} onClick={() => action('start')}>시작</button>
      <button disabled={busy || state !== 'RUNNING'} onClick={() => action('pause')}>일시정지</button>
      <button disabled={busy || state !== 'PAUSED' || !usable} onClick={() => action('resume')}>재개</button>
      <button disabled={busy || !mission || ['CANCELED', 'COMPLETED'].includes(state)} onClick={() => action('cancel')}>취소</button>
    </div>
    {!usable && <p className="map-warning">READY 편대, 제어권, 지도 목표가 모두 필요합니다.</p>}
  </section>
}
