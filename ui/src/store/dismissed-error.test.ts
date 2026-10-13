import { describe, expect, it } from 'vitest'
import { isDismissed, laterDismissal } from './dismissed-error'

describe('isDismissed', () => {
  const at = '2026-10-13T21:04:05.123456Z'

  it('nothing is dismissed before the first dismissal', () => {
    expect(isDismissed(at, null)).toBe(false)
  })
  it('covers the dismissed error and older ones', () => {
    expect(isDismissed(at, at)).toBe(true)
    expect(isDismissed('2026-10-13T20:00:00Z', at)).toBe(true)
  })
  it('a newer error still pops up', () => {
    expect(isDismissed('2026-10-13T21:04:06Z', at)).toBe(false)
  })
  it('compares instants, not strings', () => {
    expect(isDismissed('2026-10-13T23:04:05+02:00', '2026-10-13T21:04:05.5Z')).toBe(true)
  })
  it('an unreadable time is never taken as dismissed', () => {
    expect(isDismissed('garbage', at)).toBe(false)
    expect(isDismissed(at, 'garbage')).toBe(false)
  })
})

describe('laterDismissal', () => {
  it('keeps the later of the two', () => {
    expect(laterDismissal(null, '2026-10-13T21:00:00Z')).toBe('2026-10-13T21:00:00Z')
    expect(laterDismissal('2026-10-13T22:00:00Z', '2026-10-13T21:00:00Z')).toBe('2026-10-13T22:00:00Z')
    expect(laterDismissal('2026-10-13T20:00:00Z', '2026-10-13T21:00:00Z')).toBe('2026-10-13T21:00:00Z')
  })
})
