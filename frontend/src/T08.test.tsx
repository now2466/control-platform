import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import AlertList from './AlertList'
import MapPanel from './MapPanel'

afterEach(() => { cleanup(); vi.restoreAllMocks() })

const metadata = { map_id: 'mock_lab', name: 'Mock Lab', frame_id: 'map', resolution: .1, width: 20, height: 20, origin: { x: 0, y: 0, yaw: 0 }, version: '1', data_url: '/api/v1/maps/mock_lab/data' }
const robot = { robot_id: 'robot_1', name: 'Pinky Master', role: 'MASTER' as const, pose: { x: 1, y: 1, yaw: 0 }, pose_freshness: 'FRESH', tf_valid: true }

test('acknowledging an alert leaves its active cause visible', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ alert_id: 'a1', code: 'TF_INVALID', severity: 'CRITICAL', state: 'ACTIVE', acknowledged_by: 'operator', acknowledged_at: '2026-01-01T00:00:00Z', message: 'TF 변환을 확인할 수 없습니다.', first_seen_at: '2026-01-01T00:00:00Z', last_seen_at: '2026-01-01T00:00:00Z', occurrences: 1 }), { status: 200 }))
  render(<AlertList alerts={[{ alert_id: 'a1', code: 'TF_INVALID', severity: 'CRITICAL', state: 'ACTIVE', message: 'TF 변환을 확인할 수 없습니다.', occurrences: 1 }]} onError={() => {}} />)
  fireEvent.click(screen.getByRole('button', { name: '확인' }))
  await waitFor(() => expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/alerts/a1/ack'))
  await waitFor(() => expect(screen.getByText(/확인: operator/)).toBeTruthy())
  expect(screen.getByText('TF 변환을 확인할 수 없습니다.')).toBeTruthy()
})

test('selected robot scan and costmap overlays fetch once and show unsupported state clearly', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
    const url = String(input)
    if (url.includes('/sensor-layers')) return Promise.resolve(new Response(JSON.stringify(url.includes('robot_2') ? { robot_id: 'robot_2', scan: { state: 'UNSUPPORTED', rays: [] }, costmaps: [{ name: 'local_costmap', state: 'UNSUPPORTED', cells: [] }, { name: 'global_costmap', state: 'UNSUPPORTED', cells: [] }] } : { robot_id: 'robot_1', scan: { state: 'OK', rays: [{ angle_rad: 0, range_m: 1 }] }, costmaps: [{ name: 'local_costmap', state: 'OK', cells: [{ x: 1.5, y: 1.5, occupied: true }] }, { name: 'global_costmap', state: 'OK', cells: [] }] }), { status: 200 }))
    return Promise.resolve(new Response(JSON.stringify(metadata), { status: 200 }))
  })
  const { rerender } = render(<MapPanel robots={[robot]} selected="robot_1" mapId="mock_lab" onSelect={() => {}} />)
  fireEvent.click(screen.getByRole('button', { name: 'Scan' }))
  await waitFor(() => expect(fetchMock.mock.calls.some(call => call[0] === '/api/v1/robots/robot_1/sensor-layers')).toBe(true))
  expect(screen.getByText(/Scan · OK/)).toBeTruthy()
  rerender(<MapPanel robots={[robot, { ...robot, robot_id: 'robot_2', name: 'Pinky Slave', role: 'SLAVE' as const }]} selected="robot_2" mapId="mock_lab" onSelect={() => {}} />)
  await waitFor(() => expect(fetchMock.mock.calls.some(call => call[0] === '/api/v1/robots/robot_2/sensor-layers')).toBe(true))
  expect(screen.getByText(/지원하지 않음/)).toBeTruthy()
})

test('changing selection clears old sensor layers and ignores a mismatched response', async () => {
  let resolveSecond: ((value: Response) => void) | undefined
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
    const url = String(input)
    if (!url.includes('/sensor-layers')) return Promise.resolve(new Response(JSON.stringify(metadata), { status: 200 }))
    if (url.includes('robot_1')) return Promise.resolve(new Response(JSON.stringify({ robot_id: 'robot_1', scan: { state: 'OK', rays: [{ angle_rad: 0, range_m: 1 }] }, costmaps: [] }), { status: 200 }))
    return new Promise<Response>(resolve => { resolveSecond = resolve })
  })
  const { rerender } = render(<MapPanel robots={[robot, { ...robot, robot_id: 'robot_2', name: 'Pinky Slave', role: 'SLAVE' as const }]} selected="robot_1" mapId="mock_lab" onSelect={() => {}} />)
  fireEvent.click(screen.getByRole('button', { name: 'Scan' }))
  await waitFor(() => expect(screen.getByText(/Scan · OK/)).toBeTruthy())
  expect(document.querySelectorAll('.scan-layer line').length).toBe(1)
  rerender(<MapPanel robots={[robot, { ...robot, robot_id: 'robot_2', name: 'Pinky Slave', role: 'SLAVE' as const }]} selected="robot_2" mapId="mock_lab" onSelect={() => {}} />)
  expect(screen.getByText(/상태 확인 중/)).toBeTruthy()
  expect(document.querySelectorAll('.scan-layer line').length).toBe(0)
  resolveSecond?.(new Response(JSON.stringify({ robot_id: 'robot_1', scan: { state: 'OK', rays: [{ angle_rad: 0, range_m: 1 }] }, costmaps: [] }), { status: 200 }))
  await waitFor(() => expect(fetchMock.mock.calls.some(call => call[0] === '/api/v1/robots/robot_2/sensor-layers')).toBe(true))
  expect(screen.getByText(/상태 확인 중/)).toBeTruthy()
  expect(document.querySelectorAll('.scan-layer line').length).toBe(0)
})
