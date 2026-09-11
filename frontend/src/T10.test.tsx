import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import '@testing-library/jest-dom/vitest'
import { afterEach, expect, test, vi } from 'vitest'
import HistoryPanel from './HistoryPanel'

afterEach(() => { cleanup(); vi.restoreAllMocks() })

test('history filters records and downloads the filtered JSON export', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
    const path = String(input)
    if (path.includes('/export')) return Promise.resolve(new Response(JSON.stringify({ items: [] }), { status: 200, headers: { 'content-type': 'application/json' } }))
    return Promise.resolve(new Response(JSON.stringify({ items: [{ event_id: 3, event_type: 'COMMAND_SUCCEEDED', robot_id: 'robot_1', mission_id: null, occurred_at: '2026-09-11T00:00:00+00:00', payload: { target: 'robot_1' } }], next_cursor: null }), { status: 200 }))
  })
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
  render(<HistoryPanel robots={[{ robot_id: 'robot_1', name: 'Master' }]} onError={() => {}} />)
  await screen.findByText('COMMAND_SUCCEEDED')
  fireEvent.change(screen.getByLabelText('이력 유형'), { target: { value: 'COMMAND_SUCCEEDED' } })
  fireEvent.click(screen.getByRole('button', { name: '조회' }))
  await waitFor(() => expect(fetchMock.mock.calls.some(([path]) => String(path).includes('event_type=COMMAND_SUCCEEDED'))).toBe(true))
  fireEvent.click(screen.getByRole('button', { name: 'JSON 다운로드' }))
  await waitFor(() => expect(fetchMock.mock.calls.some(([path]) => String(path).includes('/api/v1/history/export'))).toBe(true))
  expect(click).toHaveBeenCalled()
})
