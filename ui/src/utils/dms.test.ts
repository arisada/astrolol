import { describe, expect, it } from 'vitest'
import { flipSign, fromParts, normalise, parseField, stepParts, toParts } from './dms'

const p = (deg: number, min: number, sec: number, negative = false) => ({ deg, min, sec, negative })

describe('toParts / fromParts', () => {
  it('splits a decimal angle', () => {
    expect(toParts(41.269166)).toEqual(p(41, 16, 9, false))
    expect(toParts(-0.5)).toEqual(p(0, 30, 0, true))
  })
  it('round-trips to 0.1 arc-second', () => {
    for (const v of [0, 12.5, -33.8688, 89.99, 179.9999, 48.123456]) {
      expect(Math.abs(fromParts(toParts(v), 'lon') - v)).toBeLessThan(0.05 / 3600)
    }
  })
  it('keeps the sign of a negative value that rounds to nothing off zero', () => {
    expect(toParts(-0.00001).negative).toBe(true)
  })
})

describe('normalise', () => {
  it('carries overflowing seconds and minutes', () => {
    expect(normalise(p(10, 59, 60), 'lat')).toEqual(p(11, 0, 0))
    expect(normalise(p(10, 75, 0), 'lat')).toEqual(p(11, 15, 0))
    expect(normalise(p(0, 0, 3725), 'lat')).toEqual(p(1, 2, 5))
  })
  it('clamps latitude and longitude', () => {
    expect(normalise(p(95, 10, 0), 'lat')).toEqual(p(90, 0, 0))
    expect(normalise(p(90, 0, 0.1), 'lat')).toEqual(p(90, 0, 0))
    expect(normalise(p(200, 0, 0, true), 'lon')).toEqual(p(180, 0, 0, true))
  })
  it('wraps right ascension at 24 h and is never negative', () => {
    expect(normalise(p(24, 0, 0), 'ra')).toEqual(p(0, 0, 0))
    expect(normalise(p(23, 59, 60), 'ra')).toEqual(p(0, 0, 0))
    expect(normalise(p(25, 30, 0), 'ra')).toEqual(p(1, 30, 0))
    expect(normalise(p(1, 0, 0, true), 'ra').negative).toBe(false)
  })
})

describe('stepParts', () => {
  it('carries 59" + 1" into the minutes, keeping tenths exact', () => {
    expect(stepParts(p(10, 20, 59), 'sec', 1, 'lat')).toEqual(p(10, 21, 0))
    expect(stepParts(p(10, 20, 59.9), 'sec', 1, 'lat')).toEqual(p(10, 21, 0.9))
  })
  it('carries 59 min up into degrees and borrows back down', () => {
    expect(stepParts(p(10, 59, 30), 'min', 1, 'lat')).toEqual(p(11, 0, 30))
    expect(stepParts(p(11, 0, 30), 'min', -1, 'lat')).toEqual(p(10, 59, 30))
  })
  it('steps seconds by one whole second', () => {
    expect(stepParts(p(0, 0, 9), 'sec', 1, 'lat')).toEqual(p(0, 0, 10))
  })
  it('stops at the poles', () => {
    expect(stepParts(p(89, 59, 30), 'min', 1, 'lat')).toEqual(p(90, 0, 0))
    expect(stepParts(p(90, 0, 0), 'deg', 1, 'lat')).toEqual(p(90, 0, 0))
    expect(stepParts(p(90, 0, 0, true), 'deg', -1, 'lat')).toEqual(p(90, 0, 0, true))
  })
  it('crosses zero and flips the sign', () => {
    expect(stepParts(p(0, 0, 30, true), 'min', 1, 'lat')).toEqual(p(0, 0, 30, false))
    expect(stepParts(p(0, 0, 30), 'min', -1, 'lat')).toEqual(p(0, 0, 30, true))
    expect(stepParts(p(0, 0, 30), 'sec', -1, 'lat')).toEqual(p(0, 0, 29, false))
    expect(stepParts(p(0, 0, 1), 'sec', -1, 'lat')).toEqual(p(0, 0, 0, false))
  })
  it('wraps right ascension in both directions', () => {
    expect(stepParts(p(23, 59, 59), 'sec', 1, 'ra')).toEqual(p(0, 0, 0))
    expect(stepParts(p(0, 0, 0), 'min', -1, 'ra')).toEqual(p(23, 59, 0))
    expect(stepParts(p(23, 0, 0), 'deg', 1, 'ra')).toEqual(p(0, 0, 0))
  })
})

describe('flipSign / parseField', () => {
  it('flips N/S but not RA', () => {
    expect(flipSign(p(10, 0, 0), 'lat').negative).toBe(true)
    expect(flipSign(p(10, 0, 0), 'ra').negative).toBe(false)
  })
  it('treats empty and invalid input as zero', () => {
    expect(parseField('', 'deg')).toBe(0)
    expect(parseField('abc', 'min')).toBe(0)
    expect(parseField('-5', 'min')).toBe(0)
    expect(parseField('12.34', 'sec')).toBe(12.3)
    expect(parseField('75', 'min')).toBe(75)
  })
})
