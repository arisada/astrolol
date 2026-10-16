import { describe, expect, it } from 'vitest'
import { fmtHA } from './meridian'

describe('fmtHA', () => {
  it('has a placeholder without a value', () => {
    expect(fmtHA(null)).toBe('—')
    expect(fmtHA(undefined)).toBe('—')
  })
  it('signs west positive and east negative', () => {
    expect(fmtHA(1.25)).toBe('+1h 15m')
    expect(fmtHA(-2.5)).toBe('−2h 30m')
  })
  it('drops the hours under one hour', () => {
    expect(fmtHA(0.2)).toBe('+12m')
    expect(fmtHA(-0.5)).toBe('−30m')
  })
})
