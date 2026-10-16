import { describe, expect, it } from 'vitest'
import type { LogEntry } from '@/store'
import { PEEK_ALERT_MS, PEEK_INFO_MS, logPageKey, peekDuration, selectEntries } from './log'

const e = (id: string, component: string, level = 'info'): LogEntry =>
  ({ id, timestamp: '2026-10-16T12:00:00Z', level, component, message: id, eventType: 'x.y' })

// The store keeps the newest entry first.
const log = [e('d', 'mount', 'error'), e('c', 'indi'), e('b', 'mount', 'warning'), e('a', 'mount')]

describe('selectEntries', () => {
  it('returns oldest first', () => {
    expect(selectEntries(log).map((x) => x.id)).toEqual(['a', 'b', 'c', 'd'])
  })
  it('filters by component', () => {
    expect(selectEntries(log, ['mount']).map((x) => x.id)).toEqual(['a', 'b', 'd'])
  })
  it('filters by level', () => {
    expect(selectEntries(log, undefined, ['warning', 'error']).map((x) => x.id)).toEqual(['b', 'd'])
  })
  it('combines both and does not touch its input', () => {
    expect(selectEntries(log, ['mount'], ['error']).map((x) => x.id)).toEqual(['d'])
    expect(log.map((x) => x.id)).toEqual(['d', 'c', 'b', 'a'])
  })
})

describe('peekDuration', () => {
  it('keeps alerts open longer', () => {
    expect(peekDuration('info')).toBe(PEEK_INFO_MS)
    expect(peekDuration('debug')).toBe(PEEK_INFO_MS)
    expect(peekDuration('warning')).toBe(PEEK_ALERT_MS)
    expect(peekDuration('error')).toBe(PEEK_ALERT_MS)
  })
})

describe('logPageKey', () => {
  it('is the first segment of the route', () => {
    expect(logPageKey('/mount')).toBe('mount')
    expect(logPageKey('/imaging/cam1')).toBe('imaging')
    expect(logPageKey('/')).toBe('home')
  })
})
