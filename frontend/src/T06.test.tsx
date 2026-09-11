import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import '@testing-library/jest-dom/vitest'
import { afterEach, expect, test, vi } from 'vitest'
import FormationPanel from './FormationPanel'
import MissionPanel from './MissionPanel'
import { waitForCommand } from './api'

afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

test('formation exposes LOST reason and only enables rejoin with lease', () => {
  render(<FormationPanel formation={{ state: 'LOST', reason_code: 'SLAVE_NOT_READY' }} lease={null} onAction={async () => {}} />)
  expect(screen.getByText(/LOST/)).toBeInTheDocument()
  expect(screen.getByText(/SLAVE_NOT_READY/)).toBeInTheDocument()
  expect(screen.getByText('재합류')).toBeDisabled()
})

test('formation exposes pause while following and unpair only after motion stops', async () => {
  const action = vi.fn().mockResolvedValue(undefined)
  const view = render(<FormationPanel formation={{ state: 'FOLLOWING' }} lease="lease-1" onAction={action} />)
  expect(screen.getByText('일시정지')).toBeEnabled()
  expect(screen.getByText('편대 해제')).toBeDisabled()
  fireEvent.click(screen.getByText('일시정지'))
  await waitFor(() => expect(action).toHaveBeenCalledWith('pause'))
  view.rerender(<FormationPanel formation={{ state: 'PAUSED' }} lease="lease-1" onAction={action} />)
  expect(screen.getByText('편대 해제')).toBeEnabled()
})

test('mission waits for queued command completion before refreshing state', async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify({ mission_id: 'm1', state: 'DRAFT' }), { status: 201 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ command_id: 'c-validate', state: 'QUEUED' }), { status: 202 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ command_id: 'c-validate', state: 'QUEUED' }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ command_id: 'c-validate', state: 'SUCCEEDED' }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ mission_id: 'm1', state: 'READY' }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ command_id: 'c-start', state: 'QUEUED' }), { status: 202 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ command_id: 'c-start', state: 'QUEUED' }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ command_id: 'c-start', state: 'SUCCEEDED' }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ mission_id: 'm1', state: 'RUNNING' }), { status: 200 }))
  vi.stubGlobal('fetch', fetchMock)
  vi.stubGlobal('crypto', { randomUUID: () => 'request-id' })
  render(<MissionPanel lease="lease-1" mapId="mock_lab" formation={{ state: 'READY' }} goal={{ x: 1, y: 2, yaw: 0, frame_id: 'map' }} onError={() => {}} />)
  fireEvent.click(screen.getByText('임무 생성'))
  await screen.findByText(/DRAFT/)
  fireEvent.click(screen.getByText('검증'))
  await screen.findByText(/READY/)
  expect(fetchMock.mock.calls.slice(1, 5).map(call => call[0])).toEqual(['/api/v1/missions/m1/actions', '/api/v1/commands/c-validate', '/api/v1/commands/c-validate', '/api/v1/missions/m1'])
  fireEvent.click(screen.getByText('시작'))
  await screen.findByText(/RUNNING/)
  expect(fetchMock.mock.calls.slice(5).map(call => call[0])).toEqual(['/api/v1/missions/m1/actions', '/api/v1/commands/c-start', '/api/v1/commands/c-start', '/api/v1/missions/m1'])
})

test('mission command failure refreshes FAILED mission and preserves failure details', async () => {
  const onError = vi.fn()
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify({ mission_id: 'm1', state: 'DRAFT' }), { status: 201 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ command_id: 'c1' }), { status: 202 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ command_id: 'c1', state: 'FAILED', reason_code: 'FOLLOW_REJECTED' }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ mission_id: 'm1', state: 'FAILED', failure_code: 'FOLLOW_REJECTED', waypoint_index: 1, waypoints: [{ x: 1, y: 2, yaw: 0, frame_id: 'map' }, { x: 2, y: 3, yaw: 0, frame_id: 'map' }, { x: 3, y: 4, yaw: 0, frame_id: 'map' }] }), { status: 200 }))
  vi.stubGlobal('crypto', { randomUUID: () => 'request-id' })
  vi.stubGlobal('fetch', fetchMock)
  render(<MissionPanel lease="lease-1" mapId="mock_lab" formation={{ state: 'READY' }} goal={{ x: 1, y: 2, yaw: 0, frame_id: 'map' }} onError={onError} />)
  fireEvent.click(screen.getByText('임무 생성'))
  await screen.findByText(/DRAFT/)
  fireEvent.click(screen.getByText('검증'))
  await waitFor(() => expect(onError).toHaveBeenCalledWith('FOLLOW_REJECTED'))
  await waitFor(() => expect(screen.getByText(/임무 · FAILED/)).toBeInTheDocument())
  expect(screen.getByTestId('mission-progress')).toHaveTextContent('현재 2/3')
  expect(screen.getByRole('alert')).toHaveTextContent('FOLLOW_REJECTED')
  expect(fetchMock.mock.calls.map(call => call[0])).toContain('/api/v1/missions/m1')
})

test('command polling reports a bounded timeout', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ command_id: 'late', state: 'QUEUED' }), { status: 200 })))
  await expect(waitForCommand('late', 1, 0)).rejects.toThrow('명령 완료 시간 초과')
})

test('mission needs a lease and READY formation before create', () => {
  render(<MissionPanel lease={null} mapId="mock_lab" formation={{ state: 'UNPAIRED' }} goal={{ x: 1, y: 2, yaw: 0, frame_id: 'map' }} onError={() => {}} />)
  expect(screen.getByText('임무 생성')).toBeDisabled()
  expect(screen.getByText('시작')).toBeDisabled()
})
