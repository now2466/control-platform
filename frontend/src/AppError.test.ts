import { describe, expect, test } from 'vitest'
import { dashboardErrorMessage } from './App'

describe('dashboard error messages', () => {
  test('does not mislabel a navigation failure as a stopped backend', () => {
    expect(dashboardErrorMessage('STOP_LATCHED')).toBe('STOP_LATCHED')
    expect(dashboardErrorMessage('명령 완료 시간 초과')).toBe('명령 완료 시간 초과')
  })

  test('shows backend guidance only for an actual network fetch failure', () => {
    expect(dashboardErrorMessage('Failed to fetch')).toContain('127.0.0.1:8081')
  })
})
