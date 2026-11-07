import { describe, expect, it } from 'vitest'
import { formatClock, formatDate, formatDateTime } from './datetime'

const T = '2026-11-07T13:57:53Z'
const utc = { timeZone: 'UTC' }

describe('datetime', () => {
  it('writes English dates day first with the month as a word, not mm/dd/yyyy', () => {
    expect(formatDate(T, 'en', utc)).toBe('7 Nov 2026')
    expect(formatDate('2026-03-04T12:00:00Z', 'en', utc)).toBe('4 Mar 2026')
  })

  it('writes the clock on 24 hours', () => {
    expect(formatClock(T, 'en', utc)).toBe('13:57')
    expect(formatClock(T, 'en', { ...utc, seconds: true })).toBe('13:57:53')
    expect(formatClock('2026-11-07T00:05:00Z', 'en', utc)).toBe('00:05')
  })

  it('joins both', () => {
    expect(formatDateTime(T, 'en', utc)).toBe('7 Nov 2026, 13:57')
  })

  it('follows the language otherwise', () => {
    expect(formatDate(T, 'fr', utc)).toMatch(/^7 nov\.? 2026$/)
    expect(formatDateTime(T, 'fr', utc)).toContain('13:57')
  })
})
