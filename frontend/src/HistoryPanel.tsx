import { useEffect, useState } from 'react'
import { downloadHistory, getHistory } from './api'
import type { HistoryEvent, HistoryFilters } from './api'

type Robot = { robot_id: string; name: string }
const labels: Record<string, string> = { COMMAND_ACCEPTED: '명령 접수', COMMAND_RUNNING: '명령 실행', COMMAND_SUCCEEDED: '명령 성공', COMMAND_FAILED: '명령 실패', COMMAND_RESULT: '명령 결과', MISSION_CREATED: '임무 생성', MISSION_TRANSITION: '임무 전이', FORMATION_CHANGED: '편대 변경', ALERT_ACTIVE: '경고 활성', ALERT_RESOLVED: '경고 해소', ALERT_ACK: '경고 확인', SETTINGS_UPDATED: '설정 변경', MAP_ACTIVATED: '지도 활성화', INITIAL_POSE_REQUESTED: '초기 위치 요청', SAFETY_STOP: '보호 정지' }

export default function HistoryPanel({ robots, onError }: { robots: Robot[]; onError: (message: string) => void }) {
  const [filters, setFilters] = useState<HistoryFilters>({})
  const [items, setItems] = useState<HistoryEvent[]>([])
  const [next, setNext] = useState<number | null>(null)
  const load = (cursor?: number, append = false) => getHistory(filters, cursor).then(value => { setItems(current => append ? [...current, ...value.items] : value.items); setNext(value.next_cursor) }).catch(error => onError((error as Error).message))
  useEffect(() => { load() }, [])
  const set = (key: keyof HistoryFilters, value: string) => setFilters(current => ({ ...current, [key]: value || undefined }))
  return <section className="history-panel" aria-label="운용 이력">
    <div className="section-title"><h2>운용 이력</h2><span>기본 최근 24시간 · 최대 30일</span></div>
    <div className="history-filters">
      <label>이력 유형<select aria-label="이력 유형" value={filters.event_type ?? ''} onChange={event => set('event_type', event.target.value)}><option value="">전체</option>{Object.keys(labels).map(value => <option key={value} value={value}>{labels[value]}</option>)}</select></label>
      <label>로봇<select aria-label="로봇 이력" value={filters.robot_id ?? ''} onChange={event => set('robot_id', event.target.value)}><option value="">전체</option>{robots.map(robot => <option key={robot.robot_id} value={robot.robot_id}>{robot.name}</option>)}</select></label>
      <label>임무 ID<input aria-label="임무 ID" value={filters.mission_id ?? ''} onChange={event => set('mission_id', event.target.value)} /></label>
      <label>시작 UTC<input aria-label="시작 UTC" type="datetime-local" onChange={event => set('from', event.target.value ? new Date(event.target.value).toISOString() : '')} /></label>
      <label>종료 UTC<input aria-label="종료 UTC" type="datetime-local" onChange={event => set('to', event.target.value ? new Date(event.target.value).toISOString() : '')} /></label>
    </div>
    <button onClick={() => load()}>조회</button><button onClick={() => downloadHistory(filters).catch(error => onError((error as Error).message))}>JSON 다운로드</button>
    {!items.length ? <p className="map-note">표시할 이력이 없습니다.</p> : <div className="history-items">{items.map(item => <article className="history-item" key={item.event_id}><div><b>{labels[item.event_type] ?? item.event_type}</b><strong>{item.event_type}</strong><p>{item.robot_id ?? '공통'}{item.mission_id ? ` · ${item.mission_id}` : ''}</p></div><div><time>{new Date(item.occurred_at).toLocaleString('ko-KR')}</time><small>{Object.entries(item.payload).filter(([key]) => key !== 'result').map(([key, value]) => `${key}: ${String(value)}`).join(' · ')}</small></div></article>)}</div>}
    {next && <button onClick={() => load(next, true)}>더 보기</button>}
  </section>
}
