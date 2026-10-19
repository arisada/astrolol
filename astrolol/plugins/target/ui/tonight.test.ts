import { describe, expect, it } from 'vitest'
import type { TonightItem } from './api'
import { firstNearMoon, fmtMag, fmtSize, timing } from './tonight'

const item = (over: Partial<TonightItem> = {}): TonightItem => ({
  name: 'M 31', aliases: [], type: 'Galaxy', ra: 10, dec: 41, source: 'catalog', mag: null, size_arcmin: null,
  alt_now: 60, peak_alt: 80, peak_time: '2026-10-18T22:00:00+00:00', rise_time: null, set_time: null,
  moon_separation: 80, near_moon: false, ...over,
})

describe('tonight helpers', () => {
  it('an object already up is "up", one still to rise is "rises"', () => {
    expect(timing(item()).state).toBe('up')
    expect(timing(item({ rise_time: '2026-10-18T23:00:00+00:00' })).state).toBe('rises')
    expect(timing(item({ set_time: 'x' })).sets).toBe('x')
  })

  it('finds where the Moon-spoiled objects start', () => {
    expect(firstNearMoon([item(), item({ near_moon: true }), item({ near_moon: true })])).toBe(1)
    expect(firstNearMoon([item()])).toBe(-1)
  })

  it('formats magnitude and size, and nothing when unknown', () => {
    expect(fmtMag(3.44)).toBe('3.4')
    expect(fmtMag(null)).toBeNull()
    expect(fmtSize(177.8)).toBe('3.0°')
    expect(fmtSize(100)).toBe('100′')
    expect(fmtSize(3.2)).toBe('3.2′')
    expect(fmtSize(240)).toBe('4.0°')
    expect(fmtSize(null)).toBeNull()
    expect(fmtSize(0)).toBeNull()
  })
})
