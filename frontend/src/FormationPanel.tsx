import { useState } from 'react'
import type { Formation } from './api'

type Action = 'pair' | 'pause' | 'unpair' | 'rejoin'

export default function FormationPanel({ formation, lease, onAction }: { formation?: Formation; lease: string | null; onAction: (action: Action) => Promise<void> }) {
  const [busy, setBusy] = useState(false)
  const state = formation?.state ?? 'UNKNOWN'
  const run = async (action: Action) => {
    setBusy(true)
    try { await onAction(action) } finally { setBusy(false) }
  }
  const can = (allowed: string[]) => !busy && Boolean(lease) && allowed.includes(state)
  return <section className="formation-panel">
    <h2>편대 상태 · {state}</h2>
    <p>거리: {formation?.distance_m == null ? '—' : `${formation.distance_m.toFixed(2)}m`} · 방위각: {formation?.bearing_rad == null ? '—' : `${formation.bearing_rad.toFixed(2)}rad`}</p>
    {formation?.reason_code && <strong>{formation.reason_code}</strong>}
    <p className="map-note">마스터: {formation?.master_id ?? 'robot_1'} · 슬레이브: {formation?.slave_id ?? 'robot_2'}</p>
    <button disabled={!can(['UNPAIRED', 'STOPPED'])} onClick={() => run('pair')}>편대 구성</button>
    <button disabled={!can(['FOLLOWING'])} onClick={() => run('pause')}>일시정지</button>
    <button disabled={!can(['READY', 'PAUSED', 'STOPPED'])} onClick={() => run('unpair')}>편대 해제</button>
    <button disabled={!can(['LOST'])} onClick={() => run('rejoin')}>재합류</button>
    {!lease && <p className="map-warning">편대 제어에는 제어권이 필요합니다.</p>}
  </section>
}
