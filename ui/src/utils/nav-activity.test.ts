import { describe, expect, it } from 'vitest'
import { deviceActivity, worstActivity } from './nav-activity'

describe('worstActivity', () => {
  it('is null when nothing is going on', () => {
    expect(worstActivity([])).toBeNull()
    expect(worstActivity([null, null])).toBeNull()
  })
  it('an alert beats busy, busy beats nothing', () => {
    expect(worstActivity([null, 'busy'])).toBe('busy')
    expect(worstActivity(['busy', 'alert', null])).toBe('alert')
    expect(worstActivity(['alert', 'busy'])).toBe('alert')
  })
})

describe('deviceActivity', () => {
  it('a device in error is an alert, even while busy', () => {
    expect(deviceActivity([{ state: 'connected' }, { state: 'error' }], true)).toBe('alert')
  })
  it('otherwise follows busy', () => {
    expect(deviceActivity([{ state: 'busy' }], true)).toBe('busy')
    expect(deviceActivity([{ state: 'connected' }], false)).toBeNull()
    expect(deviceActivity([], false)).toBeNull()
  })
})
