import { describe, expect, it } from 'vitest'
import { describeNames } from './names'

describe('describeNames', () => {
  it('leads with the Messier number', () => {
    const d = describeNames('NGC 224', ['UGC 00454', 'M31', 'NGC224', 'Andromeda Galaxy', 'Messier 31', 'M 31', 'NGC0224'])
    expect(d.title).toBe('M 31')
    expect(d.others.slice(0, 2)).toEqual(['NGC 224', 'Andromeda Galaxy'])
    expect(d.others).not.toContain('M 31')
    expect(d.others.filter((n) => n.toLowerCase().startsWith('ngc'))).toEqual(['NGC 224'])
  })

  it('keeps the object name first when there is no Messier number', () => {
    const d = describeNames('NGC 188', ['MWSC 0074', 'C 001', 'NGC188'])
    expect(d.title).toBe('NGC 188')
    expect(d.others).toEqual(['C 1', 'MWSC 0074'])
  })

  it('writes Caldwell and Sharpless numbers the usual way', () => {
    const d = describeNames('Sh2-155', ['Sharpless 155', 'C 009', 'Caldwell 9', 'Cave Nebula'])
    expect(d.title).toBe('Sh2-155')
    expect(d.others).toEqual(['C 9', 'Cave Nebula'])
  })

  it('puts everyday names before survey designations', () => {
    const d = describeNames('NGC 4945', ['2MASX J13052727-4928044', 'Foo Galaxy', 'IC 1'])
    expect(d.others).toEqual(['IC 1', 'Foo Galaxy', '2MASX J13052727-4928044'])
  })

  it('copes with no aliases', () => {
    expect(describeNames('Moon', [])).toEqual({ title: 'Moon', others: [] })
  })
})
