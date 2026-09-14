import { describe, expect, test } from 'vitest'
import { dashboardErrorMessage, isRobotStill } from './App'

describe('dashboard error messages', () => {
  test('does not mislabel a navigation failure as a stopped backend', () => {
    expect(dashboardErrorMessage('STOP_LATCHED')).toBe('STOP_LATCHED')
    expect(dashboardErrorMessage('명령 완료 시간 초과')).toBe('명령 완료 시간 초과')
  })

  test('shows backend guidance only for an actual network fetch failure', () => {
    expect(dashboardErrorMessage('Failed to fetch')).toContain('127.0.0.1:8081')
  })
})

describe('robot still tolerance', () => {
  test('accepts measured Pinky encoder noise but rejects actual motion', () => {
    expect(isRobotStill(0.0013, -0.026)).toBe(true)
    expect(isRobotStill(0.011, 0)).toBe(false)
    expect(isRobotStill(0, 0.031)).toBe(false)
  })
})
