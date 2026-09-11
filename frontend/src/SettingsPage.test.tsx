import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import '@testing-library/jest-dom/vitest'
import { afterEach, expect, test, vi } from 'vitest'
import SettingsPage from './SettingsPage'

const settings = { version: 3, active_map_id: 'mock_lab', follow_distance_m: .8, follow_tolerance_m: .2, max_linear_mps: .15, max_angular_rps: .5, camera_quality: 'default' as const }
const robots = [{ robot_id: 'robot_1', name: 'Pinky Master', mode: 'IDLE', pose: { x: 1.2, y: 2, yaw: 0, frame_id: 'map' } }]

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

test('admin saves bounded settings with its optimistic version and selected static map', async () => {
  vi.stubGlobal('crypto', { randomUUID: () => 'request-1' })
  document.cookie = 'cc_csrf=test-csrf'
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
    if (String(input) === '/api/v1/settings' && !init?.method) return Promise.resolve(new Response(JSON.stringify(settings)))
    if (String(input) === '/api/v1/maps') return Promise.resolve(new Response(JSON.stringify({ items: [{ map_id: 'mock_lab', name: 'Mock Lab', version: '1' }, { map_id: 'mock_lab_b', name: 'Mock Lab B', version: '1' }] })))
    return Promise.resolve(new Response(JSON.stringify({ ...settings, version: 4, active_map_id: 'mock_lab_b', camera_quality: 'high' })))
  })
  const saved = vi.fn()
  render(<SettingsPage role="ADMIN" robots={robots} selectedRobot="robot_1" onError={() => {}} onSaved={saved} />)
  await screen.findByRole('option', { name: 'Mock Lab B' })
  fireEvent.change(screen.getByLabelText('활성 지도'), { target: { value: 'mock_lab_b' } })
  fireEvent.change(screen.getByLabelText('카메라 품질'), { target: { value: 'high' } })
  fireEvent.click(screen.getByRole('button', { name: '설정 저장' }))
  await waitFor(() => expect(saved).toHaveBeenCalledWith(expect.objectContaining({ version: 4, active_map_id: 'mock_lab_b', camera_quality: 'high' })))
  const request = fetchMock.mock.calls.find(([, init]) => init?.method === 'PUT')![1] as RequestInit
  expect(JSON.parse(request.body as string)).toMatchObject({ request_id: 'request-1', version: 3, active_map_id: 'mock_lab_b', camera_quality: 'high' })
})

test('initial pose uses the selected robot and viewers cannot mutate settings', async () => {
  vi.stubGlobal('crypto', { randomUUID: () => 'pose-request' })
  vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
    if (String(input) === '/api/v1/settings' && !init?.method) return Promise.resolve(new Response(JSON.stringify(settings)))
    if (String(input) === '/api/v1/maps') return Promise.resolve(new Response(JSON.stringify({ items: [{ map_id: 'mock_lab', name: 'Mock Lab', version: '1' }] })))
    return Promise.resolve(new Response(JSON.stringify({ command_id: 'command-1' }), { status: 202 }))
  })
  const { rerender } = render(<SettingsPage role="ADMIN" robots={robots} selectedRobot="robot_1" onError={() => {}} onSaved={() => {}} />)
  await screen.findByDisplayValue('1.2')
  fireEvent.change(screen.getByLabelText('초기 위치 X'), { target: { value: '3' } })
  fireEvent.click(screen.getByRole('button', { name: '초기 위치 적용' }))
  await waitFor(() => expect(vi.mocked(fetch).mock.calls.some(([path, init]) => String(path) === '/api/v1/robots/robot_1/initial-pose' && init?.method === 'POST')).toBe(true))
  const call = vi.mocked(fetch).mock.calls.find(([path]) => String(path).includes('initial-pose'))!
  expect(JSON.parse((call[1] as RequestInit).body as string)).toMatchObject({ request_id: 'pose-request', pose: { x: 3, y: 2, yaw: 0, frame_id: 'map' } })
  rerender(<SettingsPage role="VIEWER" robots={robots} selectedRobot="robot_1" onError={() => {}} onSaved={() => {}} />)
  expect(screen.getByRole('button', { name: '설정 저장' })).toBeDisabled()
  expect(screen.getByRole('button', { name: '초기 위치 적용' })).toBeDisabled()
})
