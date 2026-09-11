import { useEffect, useState } from 'react'
import { acknowledgeAlert } from './api'

export type DashboardAlert = {
  alert_id: string
  code: string
  severity: string
  state: string
  message: string
  robot_id?: string | null
  occurrences: number
  acknowledged_by?: string | null
  acknowledged_at?: string | null
}

export default function AlertList({ alerts, onError }: { alerts: DashboardAlert[]; onError: (message: string) => void }) {
  const [items, setItems] = useState(alerts)
  useEffect(() => setItems(alerts), [alerts])
  if (!items.length) return <section className="alert-list"><div className="section-title"><h2>최신 경고</h2><span>활성 경고 없음</span></div></section>
  return <section className="alert-list" aria-label="최신 경고"><div className="section-title"><h2>최신 경고</h2><span>{items.length}개 활성</span></div>{items.map(alert => <article className={`alert-item ${alert.severity.toLowerCase()}`} key={alert.alert_id}><div><b>{alert.severity}</b><strong>{alert.code}</strong><p>{alert.message}</p><small>{alert.robot_id ?? '공통'} · 발생 {alert.occurrences}회{alert.acknowledged_by ? ` · 확인: ${alert.acknowledged_by}` : ''}</small></div>{alert.acknowledged_at ? <span className="alert-ack">확인됨</span> : <button onClick={() => acknowledgeAlert(alert.alert_id).then(updated => setItems(current => current.map(item => item.alert_id === updated.alert_id ? updated : item))).catch(reason => onError(reason.message))}>확인</button>}</article>)}</section>
}
