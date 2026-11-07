import { describe, expect, it } from 'vitest'
import { isInactiveGuider } from './useActiveGuider'

describe('isInactiveGuider', () => {
  it('is false while the active guider is not known yet', () => {
    expect(isInactiveGuider(null, 'phd2')).toBe(false)
  })

  it('is false for the guider in use, true for the others', () => {
    const g = { active: 'guider', available: ['guider', 'phd2'] }
    expect(isInactiveGuider(g, 'guider')).toBe(false)
    expect(isInactiveGuider(g, 'phd2')).toBe(true)
  })

  it('is false when no guider is in use', () => {
    expect(isInactiveGuider({ active: null, available: [] }, 'phd2')).toBe(false)
  })
})
