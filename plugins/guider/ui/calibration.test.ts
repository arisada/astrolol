import { describe, expect, it } from 'vitest'
import { summarizeCalibration } from './calibration'

describe('summarizeCalibration', () => {
  it('reads rates in pixels per second and angles in degrees', () => {
    const s = summarizeCalibration({ ra_x: 0.012, ra_y: 0, dec_x: 0, dec_y: 0.012, dec_backlash_ms: 90 })
    expect(s.raRate).toBeCloseTo(12)
    expect(s.decRate).toBeCloseTo(12)
    expect(s.raAngle).toBeCloseTo(0)
    expect(s.decAngle).toBeCloseTo(90)
    expect(s.orthogonality).toBeCloseTo(90)
    expect(s.backlashMs).toBe(90)
  })

  it('reports a mirrored camera as the same perpendicular axes', () => {
    const s = summarizeCalibration({ ra_x: 0, ra_y: -0.014, dec_x: -0.014, dec_y: 0, dec_backlash_ms: 0 })
    expect(s.orthogonality).toBeCloseTo(90)
    expect(s.raAngle).toBeCloseTo(-90)
    expect(s.decAngle).toBeCloseTo(180)
  })

  it('shows skewed axes', () => {
    const s = summarizeCalibration({ ra_x: 0.01, ra_y: 0, dec_x: 0.005, dec_y: 0.005, dec_backlash_ms: 0 })
    expect(s.orthogonality).toBeCloseTo(45)
  })
})
