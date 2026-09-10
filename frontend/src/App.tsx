import { FormEvent, useEffect, useState } from 'react'
import { acquireLease, login, logout, releaseLease, renewLease, session, stateSocket, UserSession } from './api'
import MapPanel from './MapPanel'

type Point = { x: number; y: number }
type Robot = { robot_id: string; name: string; role: 'MASTER' | 'SLAVE'; connection: string; mode: string; battery_percent: number | null; voltage_v?: number | null; linear_mps?: number | null; angular_rps?: number | null; pose?: { x: number; y: number; yaw: number } | null; pose_freshness?: string; stop_latched: boolean; trail?: Point[]; path?: Point[]; goal?: { x: number; y: number; yaw: number; frame_id: string } | null; tf_valid?: boolean; tf_reason_code?: string | null; received_at?: string | null }
type State = { robots: Robot[]; mode: string; seq: number; server_time: string; map_id?: string | null; formation?: { distance_m: number | null; bearing_rad: number | null } }

async function getState(): Promise<State> {
  const response = await fetch('/api/v1/state')
  if (response.status === 401) throw new Error('SESSION_EXPIRED')
  if (!response.ok) throw new Error(`상태 요청 실패 (${response.status})`)
  return response.json() as Promise<State>
}

export default function App() {
  const [user, setUser] = useState<UserSession | null>(null)
  const [checking, setChecking] = useState(true)
  const [credentials, setCredentials] = useState({ username: '', password: '' })
  const [authError, setAuthError] = useState('')
  const [state, setState] = useState<State | null>(null)
  const [error, setError] = useState('')
  const [socketStatus, setSocketStatus] = useState('연결 대기')
  const [lease, setLease] = useState<{ lease_id: string; expires_at: string } | null>(null)
  const [leaseError, setLeaseError] = useState('')
  const [selectedRobot, setSelectedRobot] = useState('robot_1')
  useEffect(() => { session().then(setUser).catch(e => setAuthError(e.message)).finally(() => setChecking(false)) }, [])
  useEffect(() => { if (!user) return; let active = true; const refresh = () => getState().then(value => { if (active) { setState(value); setError('') } }).catch(e => { if (!active) return; if (e.message === 'SESSION_EXPIRED') setUser(null); else setError(e.message) }); refresh(); const stopSocket = stateSocket(value => active && setState(value), status => { setSocketStatus(status); if (status === '세션 만료') setUser(null) }); const timer = setInterval(refresh, 10000); return () => { active = false; clearInterval(timer); stopSocket(); } }, [user])
  useEffect(() => { if (!lease) return; const timer = setInterval(() => renewLease(lease.lease_id).then(setLease).catch(() => setLease(null)), 1000); return () => clearInterval(timer) }, [lease?.lease_id])
  if (checking) return <main><p>세션 확인 중입니다…</p></main>
  if (!user) return <main><section className="login"><p className="eyebrow">PINKY PRO · CONTROL CENTER</p><h1>관제 로그인</h1><form onSubmit={(event: FormEvent) => { event.preventDefault(); setAuthError(''); login(credentials.username, credentials.password).then(setUser).catch(e => setAuthError(e.message)) }}><label>아이디<input autoComplete="username" value={credentials.username} onChange={e => setCredentials({ ...credentials, username: e.target.value })} required /></label><label>비밀번호<input type="password" autoComplete="current-password" value={credentials.password} onChange={e => setCredentials({ ...credentials, password: e.target.value })} required /></label><button type="submit">로그인</button></form>{authError && <div className="error">{authError}</div>}</section></main>
  return <main>
    <header><div><p className="eyebrow">PINKY PRO · CONTROL CENTER</p><h1>2대 로봇 관제</h1></div><div className="userbar"><span>{user.username} · {user.role}</span><button onClick={() => logout().finally(() => { setUser(null); setState(null); setLease(null); setLeaseError('') })}>로그아웃</button></div></header>
    <div className="session-status"><span className="pill online">권한 {user.role}</span><span className="pill">{socketStatus}</span>{lease ? <><span className="pill online">제어권 활성</span><button onClick={() => releaseLease(lease.lease_id).finally(() => setLease(null))}>제어권 반납</button></> : <button onClick={() => acquireLease().then(setLease).catch(e => setLeaseError(e.message))}>제어권 획득</button>}</div>
    {leaseError && <div className="error">{leaseError}</div>}
    {error && <div className="error">{error}. 백엔드를 127.0.0.1:8081에서 실행해 주세요.</div>}
    <MapPanel robots={state?.robots ?? []} selected={selectedRobot} mapId={state?.map_id} onSelect={setSelectedRobot} />
    {state?.formation && <p className="formation-readout">편대 거리: {state.formation.distance_m == null ? '— (TF 확인 필요)' : `${state.formation.distance_m.toFixed(2)}m`} · 방위각: {state.formation.bearing_rad == null ? '—' : `${state.formation.bearing_rad.toFixed(2)}rad`}</p>}
    <section><div className="section-title"><h2>로봇 상태</h2><span>{state?.server_time ? new Date(state.server_time).toLocaleTimeString('ko-KR') : '—'}</span></div><div className="grid">{state?.robots.map(robot => <article className={`card ${selectedRobot === robot.robot_id ? 'selected-card' : ''}`} onClick={() => setSelectedRobot(robot.robot_id)} key={robot.robot_id}><div className="card-head"><div><h3>{robot.name}</h3><small>{robot.robot_id}</small></div><b className={robot.role.toLowerCase()}>{robot.role}</b></div><dl><div><dt>연결</dt><dd className="connection">{robot.connection}</dd></div><div><dt>모드</dt><dd>{robot.mode}</dd></div><div><dt>배터리 / 전압</dt><dd>{robot.battery_percent == null ? '—' : `${robot.battery_percent}%`} · {robot.voltage_v == null ? '—' : `${robot.voltage_v}V`}</dd></div><div><dt>속도</dt><dd>{robot.linear_mps == null ? '—' : `${robot.linear_mps}m/s`} · {robot.angular_rps == null ? '—' : `${robot.angular_rps}rad/s`}</dd></div><div><dt>위치 신선도</dt><dd>{robot.pose_freshness ?? 'UNKNOWN'}</dd></div></dl>{robot.stop_latched && <div className="stop">정지 래치</div>}</article>) ?? <div className="empty">상태를 기다리는 중입니다.</div>}</div></section>
    <section className="placeholder camera"><h2>카메라 영역</h2><p>T04에서 2열 영상 그리드를 구현합니다.</p></section>
  </main>
}
