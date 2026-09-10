import { useEffect, useState } from 'react'

type Robot = { robot_id: string; name: string; role: 'MASTER' | 'SLAVE'; connection: string; mode: string; battery_percent: number | null; stop_latched: boolean }
type State = { robots: Robot[]; mode: string; seq: number; server_time: string }

async function getState(): Promise<State> {
  const response = await fetch('/api/v1/state')
  if (!response.ok) throw new Error(`상태 요청 실패 (${response.status})`)
  return response.json() as Promise<State>
}

export default function App() {
  const [state, setState] = useState<State | null>(null)
  const [error, setError] = useState('')
  useEffect(() => { let active = true; const refresh = () => getState().then(value => { if (active) { setState(value); setError('') } }).catch(e => active && setError(e.message)); refresh(); const timer = setInterval(refresh, 2000); return () => { active = false; clearInterval(timer) } }, [])
  return <main>
    <header><div><p className="eyebrow">PINKY PRO · CONTROL CENTER</p><h1>2대 로봇 관제</h1></div><span className={`pill ${state ? 'online' : 'offline'}`}>{state ? `MOCK · seq ${state.seq}` : '백엔드 연결 중'}</span></header>
    {error && <div className="error">{error}. 백엔드를 127.0.0.1:8081에서 실행해 주세요.</div>}
    <section className="placeholder"><div className="placeholder-icon">⌖</div><h2>지도 영역</h2><p>T03에서 위치·경로·목표 표시를 구현합니다.</p></section>
    <section><div className="section-title"><h2>로봇 상태</h2><span>{state?.server_time ? new Date(state.server_time).toLocaleTimeString('ko-KR') : '—'}</span></div><div className="grid">{state?.robots.map(robot => <article className="card" key={robot.robot_id}><div className="card-head"><div><h3>{robot.name}</h3><small>{robot.robot_id}</small></div><b className={robot.role.toLowerCase()}>{robot.role}</b></div><dl><div><dt>연결</dt><dd className="connection">{robot.connection}</dd></div><div><dt>모드</dt><dd>{robot.mode}</dd></div><div><dt>배터리</dt><dd>{robot.battery_percent == null ? '—' : `${robot.battery_percent}%`}</dd></div></dl>{robot.stop_latched && <div className="stop">정지 래치</div>}</article>) ?? <div className="empty">상태를 기다리는 중입니다.</div>}</div></section>
    <section className="placeholder camera"><h2>카메라 영역</h2><p>T04에서 2열 영상 그리드를 구현합니다.</p></section>
  </main>
}
