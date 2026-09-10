export type UserSession = { user_id?: string; username: string; role: string }
export type MapMetadata = { map_id: string; name: string; frame_id: string; resolution: number; width: number; height: number; origin: { x: number; y: number; yaw: number }; version: string; data_url: string }

async function errorMessage(response: Response, fallback: string) {
  try { const body = await response.json(); return body?.error?.message ?? body?.detail ?? fallback } catch { return fallback }
}

function csrf() {
  return document.cookie.split('; ').find(value => value.startsWith('cc_csrf='))?.split('=')[1] ?? ''
}

export async function session(): Promise<UserSession | null> {
  const response = await fetch('/api/v1/session', { credentials: 'include' })
  if (response.status === 401) return null
  if (!response.ok) throw new Error(await errorMessage(response, `세션 조회 실패 (${response.status})`))
  const value = await response.json()
  return value.user ?? value
}

export async function login(username: string, password: string): Promise<UserSession> {
  const response = await fetch('/api/v1/session', { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username, password }) })
  if (response.status === 401) throw new Error(await errorMessage(response, '아이디 또는 비밀번호가 올바르지 않습니다.'))
  if (!response.ok) throw new Error(await errorMessage(response, `로그인 실패 (${response.status})`))
  const value = await response.json()
  return value.user ?? value
}

export async function mapMetadata(mapId: string): Promise<MapMetadata> {
  const response = await fetch(`/api/v1/maps/${mapId}`, { credentials: 'include' })
  if (!response.ok) throw new Error(await errorMessage(response, `지도 조회 실패 (${response.status})`))
  return response.json() as Promise<MapMetadata>
}

export async function logout() {
  await fetch('/api/v1/session', { method: 'DELETE', credentials: 'include', headers: { 'X-CSRF-Token': csrf() } })
}

export async function acquireLease() {
  const response = await fetch('/api/v1/control-lease', { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf() }, body: JSON.stringify({ request_id: crypto.randomUUID() }) })
  if (response.status === 409) throw new Error('다른 사용자가 제어권을 사용 중입니다.')
  if (!response.ok) throw new Error(await errorMessage(response, `제어권 획득 실패 (${response.status})`))
  return response.json() as Promise<{ lease_id: string; expires_at: string }>
}

export async function releaseLease(leaseId: string) {
  await fetch(`/api/v1/control-lease/${leaseId}`, { method: 'DELETE', credentials: 'include', headers: { 'X-CSRF-Token': csrf(), 'Content-Type': 'application/json' }, body: JSON.stringify({ request_id: crypto.randomUUID() }) })
}
export async function renewLease(leaseId: string) {
  const response = await fetch(`/api/v1/control-lease/${leaseId}`, { method: 'PATCH', credentials: 'include', headers: { 'X-CSRF-Token': csrf(), 'Content-Type': 'application/json' }, body: JSON.stringify({ request_id: crypto.randomUUID() }) })
  if (!response.ok) throw new Error(await errorMessage(response, '제어권 갱신 실패'))
  return response.json() as Promise<{ lease_id: string; expires_at: string }>
}

export function stateSocket(onState: (state: any) => void, onStatus: (status: string) => void) {
  let closed = false
  let socket: WebSocket | undefined
  let retry = 1000
  const connect = () => {
    if (closed) return
    onStatus('연결 중')
    socket = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/state`)
    socket.onopen = () => { retry = 1000; onStatus('실시간 연결') }
    let lastSeq = 0
    socket.onmessage = event => { try { const message = JSON.parse(event.data); const nextSeq = Number(message.seq); if (lastSeq && nextSeq > lastSeq + 1) fetch('/api/v1/state', { credentials: 'include' }).then(response => response.ok ? response.json() : null).then(value => { if (value && Number(value.seq) >= lastSeq) onState(value) }); lastSeq = Math.max(lastSeq, nextSeq || 0); if (message.type === 'snapshot' || message.payload?.robots) onState(message.payload ?? message) } catch { /* discard malformed event */ } }
    socket.onclose = event => { if (closed) return; onStatus([1008, 4401, 4403].includes(event.code) ? '세션 만료' : '재연결 대기'); setTimeout(connect, retry); retry = Math.min(retry * 2, 8000) }
    socket.onerror = () => socket?.close()
  }
  connect()
  return () => { closed = true; socket?.close() }
}
