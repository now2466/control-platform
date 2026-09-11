import { ChangeEvent, FormEvent, useEffect, useState } from 'react'
import { ActiveSettings, getSettings, Goal, listMaps, MapSummary, setInitialPose, updateSettings } from './api'

type Robot = { robot_id: string; name: string; mode: string; pose?: { x: number; y: number; yaw: number; frame_id?: string } | null }

const initial: ActiveSettings = { version: 1, active_map_id: 'mock_lab', follow_distance_m: .8, follow_tolerance_m: .2, max_linear_mps: .15, max_angular_rps: .5, camera_quality: 'default' }

export default function SettingsPage({ role, robots, selectedRobot, onError, onSaved, onLoaded }: { role: string; robots: Robot[]; selectedRobot: string; onError: (message: string) => void; onSaved: (value: ActiveSettings) => void; onLoaded?: (value: ActiveSettings) => void }) {
  const [settings, setSettings] = useState<ActiveSettings>(initial)
  const [maps, setMaps] = useState<MapSummary[]>([])
  const [pose, setPose] = useState<Goal>({ x: 0, y: 0, yaw: 0, frame_id: 'map' })
  const [notice, setNotice] = useState('')
  const admin = role === 'ADMIN'
  const robot = robots.find(value => value.robot_id === selectedRobot)

  useEffect(() => {
    let alive = true
    Promise.all([getSettings(), listMaps()]).then(([value, available]) => {
      if (!alive) return
      setSettings(value); setMaps(available); onLoaded?.(value); setNotice('')
    }).catch(error => alive && onError((error as Error).message))
    return () => { alive = false }
  }, [])
  useEffect(() => {
    if (robot?.pose) setPose({ ...robot.pose, frame_id: robot.pose.frame_id ?? 'map' })
  }, [robot?.robot_id])

  const number = (key: 'follow_distance_m' | 'follow_tolerance_m' | 'max_linear_mps' | 'max_angular_rps') => (event: ChangeEvent<HTMLInputElement>) => setSettings(value => ({ ...value, [key]: Number(event.target.value) }))
  const save = async (event: FormEvent) => {
    event.preventDefault(); setNotice('')
    try { const value = await updateSettings(settings); setSettings(value); onSaved(value); setNotice('설정을 적용했습니다.') } catch (error) { onError((error as Error).message) }
  }
  const applyPose = async () => {
    setNotice('')
    try { await setInitialPose(selectedRobot, pose); setNotice('초기 위치 요청을 접수했습니다.') } catch (error) { onError((error as Error).message) }
  }

  return <section className="settings-panel">
    <div className="section-title"><h2>운용 설정</h2><span>버전 {settings.version}</span></div>
    {!admin && <p className="map-note">설정 조회 전용입니다. 변경에는 ADMIN 권한이 필요합니다.</p>}
    <form onSubmit={save}>
      <div className="settings-grid">
        <label>활성 지도<select aria-label="활성 지도" value={settings.active_map_id} disabled={!admin} onChange={event => setSettings(value => ({ ...value, active_map_id: event.target.value }))}>{maps.map(map => <option key={map.map_id} value={map.map_id}>{map.name}</option>)}</select></label>
        <label>추종 거리 (m)<input aria-label="추종 거리" type="number" min="0.5" max="2" step="0.05" value={settings.follow_distance_m} disabled={!admin} onChange={number('follow_distance_m')} /></label>
        <label>추종 허용 오차 (m)<input aria-label="추종 허용 오차" type="number" min="0.05" max="0.5" step="0.05" value={settings.follow_tolerance_m} disabled={!admin} onChange={number('follow_tolerance_m')} /></label>
        <label>최대 선속도 (m/s)<input aria-label="최대 선속도" type="number" min="0.01" max="1" step="0.01" value={settings.max_linear_mps} disabled={!admin} onChange={number('max_linear_mps')} /></label>
        <label>최대 각속도 (rad/s)<input aria-label="최대 각속도" type="number" min="0.01" max="2" step="0.01" value={settings.max_angular_rps} disabled={!admin} onChange={number('max_angular_rps')} /></label>
        <label>카메라 품질<select aria-label="카메라 품질" value={settings.camera_quality} disabled={!admin} onChange={event => setSettings(value => ({ ...value, camera_quality: event.target.value as ActiveSettings['camera_quality'] }))}><option value="low">low</option><option value="default">default</option><option value="high">high</option></select></label>
      </div>
      <button type="submit" disabled={!admin}>설정 저장</button>
    </form>
    <div className="initial-pose"><h3>선택 로봇 초기 위치</h3><p>{robot?.name ?? selectedRobot} · {robot?.mode ?? '상태 확인 중'} · 정지와 편대 해제 상태에서만 적용됩니다.</p><div className="settings-grid pose-grid"><label>X (m)<input aria-label="초기 위치 X" type="number" step="0.1" value={pose.x} disabled={!admin} onChange={event => setPose(value => ({ ...value, x: Number(event.target.value) }))} /></label><label>Y (m)<input aria-label="초기 위치 Y" type="number" step="0.1" value={pose.y} disabled={!admin} onChange={event => setPose(value => ({ ...value, y: Number(event.target.value) }))} /></label><label>Yaw (rad)<input aria-label="초기 위치 Yaw" type="number" min={-Math.PI} max={Math.PI} step="0.1" value={pose.yaw} disabled={!admin} onChange={event => setPose(value => ({ ...value, yaw: Number(event.target.value) }))} /></label></div><button type="button" disabled={!admin} onClick={applyPose}>초기 위치 적용</button></div>
    {notice && <p className="settings-notice">{notice}</p>}
  </section>
}
