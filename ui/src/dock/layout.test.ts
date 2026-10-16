import { describe, expect, it } from 'vitest'
import { addWidget, moveWidget, removeWidget, toggleCollapsed } from './layout'

const w = (id: string, collapsed = false) => ({ id, collapsed })

describe('dock layout', () => {
  it('adds at the end, once', () => {
    expect(addWidget([w('a.x')], 'b.y').map((e) => e.id)).toEqual(['a.x', 'b.y'])
    expect(addWidget([w('a.x')], 'a.x')).toHaveLength(1)
  })
  it('removes', () => {
    expect(removeWidget([w('a.x'), w('b.y')], 'a.x')).toEqual([w('b.y')])
  })
  it('moves, and stays put at the ends', () => {
    const l = [w('a.x'), w('b.y'), w('c.z')]
    expect(moveWidget(l, 'c.z', -1).map((e) => e.id)).toEqual(['a.x', 'c.z', 'b.y'])
    expect(moveWidget(l, 'a.x', -1)).toBe(l)
    expect(moveWidget(l, 'c.z', 1)).toBe(l)
    expect(moveWidget(l, 'nope.x', 1)).toBe(l)
  })
  it('collapses and expands', () => {
    expect(toggleCollapsed([w('a.x')], 'a.x')).toEqual([w('a.x', true)])
    expect(toggleCollapsed([w('a.x', true)], 'a.x')).toEqual([w('a.x')])
  })
})
