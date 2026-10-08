import { describe, expect, it } from 'vitest'
import { phasePoints, summarizeCalibration, traceBounds } from './calibration'
import type { CalibrationPoint } from './api'

describe('summarizeCalibration', () => {
  it('reads rates in pixels per second and angles in degrees', () => {
    const s = summarizeCalibration({ ra_x: 0.012, ra_y: 0, dec_x: 0, dec_y: 0.012, dec_backlash_ms: 90, ra_backlash_ms: 0, drift_x: 0, drift_y: 0, trace: [] })
    expect(s.raRate).toBeCloseTo(12)
    expect(s.decRate).toBeCloseTo(12)
    expect(s.raAngle).toBeCloseTo(0)
    expect(s.decAngle).toBeCloseTo(90)
    expect(s.orthogonality).toBeCloseTo(90)
    expect(s.backlashMs).toBe(90)
  })

  it('reports a mirrored camera as the same perpendicular axes', () => {
    const s = summarizeCalibration({ ra_x: 0, ra_y: -0.014, dec_x: -0.014, dec_y: 0, dec_backlash_ms: 0, ra_backlash_ms: 0, drift_x: 0, drift_y: 0, trace: [] })
    expect(s.orthogonality).toBeCloseTo(90)
    expect(s.raAngle).toBeCloseTo(-90)
    expect(s.decAngle).toBeCloseTo(180)
  })

  it('shows skewed axes', () => {
    const s = summarizeCalibration({ ra_x: 0.01, ra_y: 0, dec_x: 0.005, dec_y: 0.005, dec_backlash_ms: 0, ra_backlash_ms: 0, drift_x: 0, drift_y: 0, trace: [] })
    expect(s.orthogonality).toBeCloseTo(45)
  })
})

const pt = (phase: CalibrationPoint['phase'], step: number, x: number, y: number): CalibrationPoint =>
  ({ phase, step, pulse_ms: 0, x, y, t: step, used: true })

describe('traceBounds', () => {
  it('is square and holds every point with a margin', () => {
    const b = traceBounds([pt('west', 0, 100, 200), pt('west', 1, 112, 202)])
    expect(b.maxX - b.minX).toBeCloseTo(b.maxY - b.minY)
    expect(b.minX).toBeLessThan(100)
    expect(b.maxX).toBeGreaterThan(112)
    expect(b.minY).toBeLessThan(200)
    expect(b.maxY).toBeGreaterThan(202)
  })
  it('copes with a single point and with none', () => {
    const one = traceBounds([pt('drift', 0, 5, 5)])
    expect(one.maxX).toBeGreaterThan(one.minX)
    expect(traceBounds([]).maxX).toBeGreaterThan(traceBounds([]).minX)
  })
})

describe('phasePoints', () => {
  it('keeps one phase, in step order', () => {
    const out = phasePoints([pt('north', 2, 0, 0), pt('west', 0, 0, 0), pt('north', 1, 0, 0)], 'north')
    expect(out.map((p) => p.step)).toEqual([1, 2])
  })
})
