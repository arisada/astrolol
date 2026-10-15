import { describe, expect, it } from 'vitest'
import { fmtArcmin, knobMove } from './angle'

describe('fmtArcmin', () => {
  it('shows seconds below one arcminute', () => {
    expect(fmtArcmin(0.75)).toBe('45″')
    expect(fmtArcmin(0)).toBe('0″')
  })
  it('shows minutes and seconds up to a degree', () => {
    expect(fmtArcmin(12.5)).toBe('12′ 30″')
    expect(fmtArcmin(3)).toBe('3′')
  })
  it('shows degrees and minutes from a degree', () => {
    expect(fmtArcmin(65)).toBe('1° 05′')
    expect(fmtArcmin(150)).toBe('2° 30′')
  })
  it('ignores the sign', () => {
    expect(fmtArcmin(-12.5)).toBe('12′ 30″')
  })
  it('does not print 60″', () => {
    expect(fmtArcmin(0.999)).toBe('1′')
    expect(fmtArcmin(59.999)).toBe('1° 00′')
  })
})

describe('knobMove', () => {
  it('lowers an axis that is too high and raises one that is too low', () => {
    expect(knobMove(4, 0).vertical).toEqual({ direction: 'down', arcmin: 4 })
    expect(knobMove(-4, 0).vertical).toEqual({ direction: 'up', arcmin: 4 })
  })
  it('turns left for a positive azimuth error and right for a negative one', () => {
    expect(knobMove(0, 2.5).horizontal).toEqual({ direction: 'left', arcmin: 2.5 })
    expect(knobMove(0, -2.5).horizontal).toEqual({ direction: 'right', arcmin: 2.5 })
  })
})
