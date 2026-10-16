import { describe, expect, it } from 'vitest'
import { addWidget, moveWidget, removeWidget, toggleCollapsed } from './layout'

const w = (id: string, device_id: string | null = null, collapsed = false) => ({ id, device_id, collapsed })
const ids = (l: { id: string; device_id?: string | null }[]) => l.map((e) => (e.device_id ? `${e.id}@${e.device_id}` : e.id))

describe('dock layout', () => {
  it('adds at the end, once', () => {
    expect(ids(addWidget([w('a.x')], { id: 'b.y' }))).toEqual(['a.x', 'b.y'])
    expect(addWidget([w('a.x')], { id: 'a.x' })).toHaveLength(1)
  })
  it('pins the same widget once per device', () => {
    const one = addWidget([], { id: 'focuser.position', device_id: 'esatto' })
    const two = addWidget(one, { id: 'focuser.position', device_id: 'moonlite' })
    expect(ids(two)).toEqual(['focuser.position@esatto', 'focuser.position@moonlite'])
    expect(addWidget(two, { id: 'focuser.position', device_id: 'esatto' })).toBe(two)
  })
  it('treats a missing device and null alike', () => {
    expect(addWidget([w('a.x')], { id: 'a.x', device_id: null })).toHaveLength(1)
    expect(removeWidget([w('a.x')], { id: 'a.x' })).toEqual([])
  })
  it('removes only the matching device', () => {
    const l = [w('f.p', 'a'), w('f.p', 'b')]
    expect(ids(removeWidget(l, { id: 'f.p', device_id: 'a' }))).toEqual(['f.p@b'])
  })
  it('moves, and stays put at the ends', () => {
    const l = [w('a.x'), w('b.y'), w('c.z')]
    expect(ids(moveWidget(l, { id: 'c.z' }, -1))).toEqual(['a.x', 'c.z', 'b.y'])
    expect(moveWidget(l, { id: 'a.x' }, -1)).toBe(l)
    expect(moveWidget(l, { id: 'c.z' }, 1)).toBe(l)
    expect(moveWidget(l, { id: 'nope.x' }, 1)).toBe(l)
  })
  it('collapses one device only', () => {
    const l = [w('f.p', 'a'), w('f.p', 'b')]
    expect(toggleCollapsed(l, { id: 'f.p', device_id: 'b' })).toEqual([w('f.p', 'a'), w('f.p', 'b', true)])
  })
})
