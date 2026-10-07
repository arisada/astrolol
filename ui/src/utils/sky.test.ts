import { describe, expect, it } from 'vitest'
import { equatorialToHorizontal, horizonCurve, hourAngle, niceTicks } from './sky'

// Reference values from astropy (apparent place, `tete` frame -> AltAz).
const REF = [
  { lat: 48.0, lst: 23.770801, ra: 6.0, dec: 41.0, alt: 27.211, az: 57.897 },
  { lat: 48.0, lst: 23.770801, ra: 1.5, dec: -20.0, alt: 18.136, az: 154.373 },
  { lat: -33.9, lst: 11.207445, ra: 18.0, dec: -30.0, alt: 7.516, az: 121.263 },
  { lat: 0.0, lst: 20.955453, ra: 10.0, dec: 10.0, alt: -71.48, az: 303.141 },
  { lat: 65.0, lst: 4.327338, ra: 3.0, dec: 70.0, alt: 80.951, az: 312.219 },
]

describe('equatorialToHorizontal', () => {
  it.each(REF)('matches astropy at lat $lat', ({ lat, lst, ra, dec, alt, az }) => {
    const r = equatorialToHorizontal(lat, hourAngle(lst, ra), dec)
    expect(r.alt).toBeCloseTo(alt, 2)
    expect(r.az).toBeCloseTo(az, 2)
  })
  it('puts the visible pole at altitude = |latitude|', () => {
    expect(equatorialToHorizontal(48, 0, 90).alt).toBeCloseTo(48, 6)
    expect(equatorialToHorizontal(-33.9, 0, -90).alt).toBeCloseTo(33.9, 6)
  })
})

describe('hourAngle', () => {
  it('wraps into (-180, 180]', () => {
    expect(hourAngle(1, 23)).toBeCloseTo(30, 9)
    expect(hourAngle(23, 1)).toBeCloseTo(-30, 9)
    expect(hourAngle(12, 0)).toBeCloseTo(180, 9)
  })
})

describe('horizonCurve', () => {
  it.each([48, -33.9, 65, 10])('lies at altitude 0 for lat %s', (lat) => {
    for (const p of horizonCurve(lat, 7)) {
      expect(Math.abs(equatorialToHorizontal(lat, p.ha, p.dec).alt)).toBeLessThan(1e-6)
    }
  })
  it('is closed', () => {
    const c = horizonCurve(48)
    expect(c[0].dec).toBeCloseTo(c[c.length - 1].dec, 9)
  })
})

describe('niceTicks', () => {
  it('picks round steps', () => {
    expect(niceTicks(24000, 25000).step).toBe(200)
    expect(niceTicks(0, 50000).step).toBe(10000)
    expect(niceTicks(-30, 20).major).toEqual([-30, -20, -10, 0, 10, 20])
  })
  it('keeps ticks inside the range and minors apart from majors', () => {
    const t = niceTicks(24010, 24490)
    expect(Math.min(...t.major, ...t.minor)).toBeGreaterThanOrEqual(24010)
    expect(Math.max(...t.major, ...t.minor)).toBeLessThanOrEqual(24490)
    expect(t.minor.some((v) => t.major.includes(v))).toBe(false)
  })
})
