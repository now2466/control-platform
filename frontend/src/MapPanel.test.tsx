import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import '@testing-library/jest-dom/vitest'
import { afterEach, expect, test, vi } from 'vitest'
import MapPanel from './MapPanel'

const robot = { robot_id: 'robot_1', name: 'Pinky Master', role: 'MASTER' as const, pose: { x: 1, y: 1, yaw: 0 }, pose_freshness: 'STALE', tf_valid: false, trail: [{ x: .5, y: 1 }], path: [{ x: 1, y: 1.5 }] }

afterEach(() => { cleanup(); vi.restoreAllMocks() })

test('loads map metadata instead of hardcoding geometry and renders TF/stale state', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ map_id: 'mock_lab', name: 'Mock Lab', frame_id: 'map', resolution: .1, width: 20, height: 20, origin: { x: 0, y: 0, yaw: 0 }, version: '1', data_url: '/api/v1/maps/mock_lab/data' }), { status: 200 }))
  render(<MapPanel robots={[robot]} selected="robot_1" mapId="mock_lab" onSelect={() => {}} />)
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/v1/maps/mock_lab', { credentials: 'include' }))
  const svg = document.querySelector('svg')!
  expect(svg.getAttribute('viewBox')).toBe('0 0 20 20')
  expect(document.querySelector('image')?.getAttribute('href')).toContain('/api/v1/maps/mock_lab/data?version=1')
  expect(screen.getByText(/TF 변환을 확인할 수 없어/)).toBeTruthy()
  expect(screen.getByText(/위치 지연/)).toBeTruthy()
})

test('follow centers selected pose and click-drag creates a non-dispatched preview', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ map_id: 'mock_lab', name: 'Mock Lab', frame_id: 'map', resolution: .1, width: 20, height: 20, origin: { x: 0, y: 0, yaw: 0 }, version: '1', data_url: '/api/v1/maps/mock_lab/data' }), { status: 200 }))
  render(<MapPanel robots={[{ ...robot, pose_freshness: 'FRESH', tf_valid: true }]} selected="robot_1" mapId="mock_lab" onSelect={() => {}} />)
  await screen.findByText(/목표 미리보기/)
  const svg = document.querySelector('svg')!
  vi.spyOn(svg, 'getBoundingClientRect').mockReturnValue({ x: 0, y: 0, width: 200, height: 200, top: 0, left: 0, bottom: 200, right: 200, toJSON: () => ({}) })
  fireEvent.click(screen.getByText('선택 따라보기'))
  const inputLayer = document.querySelector('.map-input-layer')!
  fireEvent.pointerDown(inputLayer, { clientX: 120, clientY: 100 })
  fireEvent.pointerUp(inputLayer, { clientX: 160, clientY: 100 }); fireEvent.click(inputLayer, { clientX: 160, clientY: 100 })
  expect(document.querySelectorAll('.goal-preview').length).toBe(1)
})

test('map selection buttons assign a start pose and destination, and reset clears both', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ map_id: 'map_260905', name: '260905 실습 트랙', frame_id: 'map', resolution: .005, width: 542, height: 252, origin: { x: -1.355, y: -.63, yaw: 0 }, version: '1', data_url: '/api/v1/maps/map_260905/data' }), { status: 200 }))
  const onInitialPoseChange = vi.fn(), onGoalChange = vi.fn(), onResetSelections = vi.fn()
  render(<MapPanel robots={[robot]} selected="robot_1" mapId="map_260905" onSelect={() => {}} onInitialPoseChange={onInitialPoseChange} onGoalChange={onGoalChange} onResetSelections={onResetSelections} />)
  await screen.findByText(/목표 미리보기/)
  const svg = document.querySelector('svg')!
  vi.spyOn(svg, 'getBoundingClientRect').mockReturnValue({ x: 0, y: 0, width: 542, height: 252, top: 0, left: 0, bottom: 252, right: 542, toJSON: () => ({}) })
  fireEvent.click(screen.getByRole('button', { name: '시작점 설정' }))
  const inputLayer = document.querySelector('.map-input-layer')!
  fireEvent.pointerDown(inputLayer, { clientX: 100, clientY: 100 }); fireEvent.pointerUp(inputLayer, { clientX: 120, clientY: 100 }); fireEvent.click(inputLayer, { clientX: 120, clientY: 100 })
  expect(onInitialPoseChange).toHaveBeenCalledWith(expect.objectContaining({ frame_id: 'map' }))
  fireEvent.click(screen.getByRole('button', { name: '도착점 설정' }))
  fireEvent.pointerDown(inputLayer, { clientX: 300, clientY: 100 }); fireEvent.pointerUp(inputLayer, { clientX: 320, clientY: 100 }); fireEvent.click(inputLayer, { clientX: 320, clientY: 100 })
  expect(onGoalChange).toHaveBeenCalledWith(expect.objectContaining({ frame_id: 'map' }))
  fireEvent.click(screen.getByRole('button', { name: '설정 초기화' }))
  expect(onInitialPoseChange).toHaveBeenLastCalledWith(null)
  expect(onGoalChange).toHaveBeenLastCalledWith(null)
  expect(onResetSelections).toHaveBeenCalledOnce()
})

test('uses the selected robot exact map pose as the start marker', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ map_id: 'mock_lab', name: 'Mock Lab', frame_id: 'map', resolution: .1, width: 20, height: 20, origin: { x: 0, y: 0, yaw: 0 }, version: '1', data_url: '/api/v1/maps/mock_lab/data' }), { status: 200 }))
  const onInitialPoseChange = vi.fn()
  const current = { ...robot, pose: { x: 1.234, y: .876, yaw: -.42, frame_id: 'map' }, pose_freshness: 'FRESH', tf_valid: true }
  render(<MapPanel robots={[current]} selected="robot_1" mapId="mock_lab" onSelect={() => {}} onInitialPoseChange={onInitialPoseChange} />)
  await screen.findByText(/목표 미리보기/)
  fireEvent.click(screen.getByRole('button', { name: '현재 위치를 시작점으로' }))
  expect(onInitialPoseChange).toHaveBeenLastCalledWith({ x: 1.234, y: .876, yaw: -.42, frame_id: 'map' })
})

test('clicking the selected robot marker in start mode uses its exact pose', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ map_id: 'mock_lab', name: 'Mock Lab', frame_id: 'map', resolution: .1, width: 20, height: 20, origin: { x: 0, y: 0, yaw: 0 }, version: '1', data_url: '/api/v1/maps/mock_lab/data' }), { status: 200 }))
  const onInitialPoseChange = vi.fn()
  const current = { ...robot, pose: { x: 1.1, y: .9, yaw: .2 }, pose_freshness: 'FRESH', tf_valid: true }
  render(<MapPanel robots={[current]} selected="robot_1" mapId="mock_lab" onSelect={() => {}} onInitialPoseChange={onInitialPoseChange} />)
  await screen.findByText(/목표 미리보기/)
  fireEvent.click(screen.getByRole('button', { name: '시작점 설정' }))
  fireEvent.click(document.querySelector('.selected-robot')!)
  expect(onInitialPoseChange).toHaveBeenLastCalledWith({ x: 1.1, y: .9, yaw: .2, frame_id: 'map' })
})

test('navigation stays gated until a destination is selected and dispatches the request', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ map_id: 'mock_lab', name: 'Mock Lab', frame_id: 'map', resolution: .1, width: 20, height: 20, origin: { x: 0, y: 0, yaw: 0 }, version: '1', data_url: '/api/v1/maps/mock_lab/data' }), { status: 200 }))
  const onNavigate = vi.fn()
  render(<MapPanel robots={[{ ...robot, pose_freshness: 'FRESH', tf_valid: true }]} selected="robot_1" mapId="mock_lab" onSelect={() => {}} initialPose={{ x: 1, y: 1, yaw: 0, frame_id: 'map' }} onGoalChange={() => {}} onNavigate={onNavigate} navigationReady navigationStatus="" />)
  await screen.findByText(/목표 미리보기/)
  const svg = document.querySelector('svg')!
  vi.spyOn(svg, 'getBoundingClientRect').mockReturnValue({ x: 0, y: 0, width: 200, height: 200, top: 0, left: 0, bottom: 200, right: 200, toJSON: () => ({}) })
  expect(screen.getByRole('button', { name: '시작점에서 도착점으로 이동' })).toBeDisabled()
  const inputLayer = document.querySelector('.map-input-layer')!
  fireEvent.pointerDown(inputLayer, { clientX: 100, clientY: 100 }); fireEvent.click(inputLayer, { clientX: 100, clientY: 100 })
  expect(screen.getByRole('button', { name: '시작점에서 도착점으로 이동' })).toBeEnabled()
  fireEvent.click(screen.getByRole('button', { name: '시작점에서 도착점으로 이동' }))
  expect(onNavigate).toHaveBeenCalledOnce()
})

test('shows the exact localization blocker instead of a generic disabled button', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ map_id: 'mock_lab', name: 'Mock Lab', frame_id: 'map', resolution: .1, width: 20, height: 20, origin: { x: 0, y: 0, yaw: 0 }, version: '1', data_url: '/api/v1/maps/mock_lab/data' }), { status: 200 }))
  render(<MapPanel robots={[robot]} selected="robot_1" mapId="mock_lab" onSelect={() => {}} initialPose={{ x: 1, y: 1, yaw: 0, frame_id: 'map' }} localizationBlockers={['제어권이 없습니다.']} navigationBlockers={['AMCL map TF가 아직 유효하지 않습니다.']} />)
  await screen.findByText('위치 재설정 불가: 제어권이 없습니다.')
  expect(screen.getByText(/이동 불가: AMCL map TF가 아직 유효하지 않습니다./)).toBeTruthy()
  expect(screen.getByRole('button', { name: '위치 재설정(AMCL)' })).toHaveAttribute('title', '제어권이 없습니다.')
})
