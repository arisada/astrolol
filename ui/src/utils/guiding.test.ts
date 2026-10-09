import { describe, expect, it } from 'vitest'
import { fmtAgo, gridStep, gridValues, niceRange, pulseOnAxes, pulseScale, rmsOf, targetPosition } from './guiding'

describe('fmtAgo', () => {
  it('uses seconds, then minutes', () => {
    expect(fmtAgo(0.4)).toBe('0')
    expect(fmtAgo(45)).toBe('-45s')
    expect(fmtAgo(90)).toBe('-1m30s')
    expect(fmtAgo(120)).toBe('-2m')
  })
})

describe('grid', () => {
  it('keeps at most four lines each side', () => {
    for (const half of [0.25, 0.5, 1, 2, 3, 8, 16]) {
      const vals = gridValues(half)
      expect(vals.filter((v) => v > 0).length).toBeLessThanOrEqual(4 + 1)
      expect(vals).toContain(0)
      expect(vals[0]).toBeGreaterThanOrEqual(-half)
      expect(vals[0]).toBeCloseTo(-vals[vals.length - 1])
    }
  })

  it('chooses finer steps for tighter displays', () => {
    expect(gridStep(0.5)).toBeLessThan(gridStep(8))
  })
})

describe('niceRange', () => {
  it('holds the data with a margin', () => {
    expect(niceRange([0.1, -0.15])).toBe(0.5)
    expect(niceRange([0.3, -0.4])).toBe(1)
    expect(niceRange([0.8, -0.2])).toBe(2)
    expect(niceRange([0.9, -0.2])).toBe(4)
    expect(niceRange([3, -2])).toBe(8)
  })
  it('has a sensible value without data and beyond the table', () => {
    expect(niceRange([])).toBe(0.5)
    expect(niceRange([100])).toBe(230)
  })
})

describe('rmsOf', () => {
  it('is null without points', () => {
    expect(rmsOf([])).toBeNull()
  })
  it('combines the axes', () => {
    const r = rmsOf([
      { ra: 3, dec: 0, ts: '' },
      { ra: -3, dec: 4, ts: '' },
    ])!
    expect(r.ra).toBeCloseTo(3)
    expect(r.dec).toBeCloseTo(Math.sqrt(8))
    expect(r.total).toBeCloseTo(Math.hypot(3, Math.sqrt(8)))
  })
})

describe('targetPosition', () => {
  it('puts North up and East right', () => {
    const p = targetPosition({ ra: 1, dec: 1 }, 2, 100)
    expect(p.x).toBeCloseTo(50)
    expect(p.y).toBeCloseTo(-50)
    expect(p.clamped).toBe(false)
  })
  it('keeps far points on the edge', () => {
    const p = targetPosition({ ra: 30, dec: 40 }, 2, 100)
    expect(Math.hypot(p.x, p.y)).toBeCloseTo(100)
    expect(p.clamped).toBe(true)
    expect(p.x / p.y).toBeCloseTo(-30 / 40)
  })
})

describe('pulses on the graph', () => {
  const at = (raCorr?: number, decCorr?: number) => ({ ra: 0, dec: 0, ts: '', raCorr, decCorr })

  it('picks a scale that holds the longest pulse', () => {
    expect(pulseScale([at(80, -30), at(-150, 0)])).toBe(200)
    expect(pulseScale([at(1500, 0)])).toBe(2000)
    expect(pulseScale([at(9000, 0)])).toBe(9000)
  })

  it('has no scale without pulses', () => {
    expect(pulseScale([at(), at(0, 0)])).toBe(0)
  })

  it('draws a West pulse against an East error', () => {
    expect(pulseOnAxes(at(100, 40))).toEqual({ ra: -100, dec: 40 })
    expect(pulseOnAxes(at())).toEqual({ ra: 0, dec: 0 })
  })
})
