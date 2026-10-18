import { describe, expect, it } from 'vitest'
import { DEAD_ZONE, edgeDirections, readJoystick, type Orientation } from './joystick'

const o = (rotation: Orientation['rotation'], mirror = false): Orientation => ({ rotation, mirror })
const dirs = (dx: number, dy: number, ori: Orientation) => readJoystick(dx, dy, 100, ori, 5).directions

describe('orientation', () => {
  it('north is up and east is right when the view is unrotated', () => {
    expect(dirs(0, -80, o(0))).toEqual(['N'])
    expect(dirs(0, 80, o(0))).toEqual(['S'])
    expect(dirs(80, 0, o(0))).toEqual(['E'])
    expect(dirs(-80, 0, o(0))).toEqual(['W'])
  })

  it('a mirrored view swaps east and west', () => {
    expect(dirs(80, 0, o(0, true))).toEqual(['W'])
    expect(dirs(0, -80, o(0, true))).toEqual(['N'])
  })

  it('a view rotated clockwise by 90° has north on the right', () => {
    expect(dirs(80, 0, o(90))).toEqual(['N'])
    expect(dirs(0, 80, o(90))).toEqual(['E'])   // east then points down
    expect(edgeDirections(o(90))).toEqual({ top: 'W', right: 'N', bottom: 'E', left: 'S' })
  })

  it('180° puts south up', () => {
    expect(dirs(0, -80, o(180))).toEqual(['S'])
    expect(dirs(80, 0, o(180))).toEqual(['W'])
  })

  it('270° puts north on the left', () => {
    expect(dirs(-80, 0, o(270))).toEqual(['N'])
  })

  it('rotation and mirror together', () => {
    // mirrored, then 90° clockwise: north on the right, east pointing up
    expect(edgeDirections(o(90, true))).toEqual({ top: 'E', right: 'N', bottom: 'W', left: 'S' })
  })

  it('labels the four edges with four different directions in every orientation', () => {
    for (const rot of [0, 90, 180, 270] as const) for (const mirror of [false, true]) {
      const e = edgeDirections(o(rot, mirror))
      expect(new Set(Object.values(e)).size).toBe(4)
    }
  })
})

describe('speed and axes', () => {
  it('does nothing inside the dead zone', () => {
    expect(readJoystick(DEAD_ZONE * 100 - 1, 0, 100, o(0), 5)).toEqual({ directions: [], speed: null })
  })

  it('goes faster the further out, up to the fastest allowed, and no further', () => {
    const speeds = [15, 35, 55, 75, 100, 300].map((d) => readJoystick(d, 0, 100, o(0), 5).speed)
    expect(speeds).toEqual([...speeds].sort((a, b) => (a as number) - (b as number)))
    expect(speeds[0]).toBe(0)
    expect(speeds[4]).toBe(4)
    expect(speeds[5]).toBe(4)
  })

  it('spends more of the travel on the slow speeds', () => {
    const half = readJoystick(56, 0, 100, o(0), 10).speed as number
    expect(half).toBeLessThan(5)
  })

  it('a diagonal push moves both axes, a mostly straight one only the main axis', () => {
    expect(dirs(60, -60, o(0)).sort()).toEqual(['E', 'N'])
    expect(dirs(80, -20, o(0))).toEqual(['E'])
  })

  it('keeps the speed steady near a boundary until clearly past it', () => {
    const boundary = readJoystick(60, 0, 100, o(0), 5)
    const s = boundary.speed as number
    // wiggle a little around that position: with the previous speed it must not flicker
    for (const d of [58, 59, 60, 61, 62]) {
      expect(readJoystick(d, 0, 100, o(0), 5, s).speed).toBe(s)
    }
  })

  it('still changes speed when the thumb really moves', () => {
    const slow = readJoystick(30, 0, 100, o(0), 5)
    const fast = readJoystick(95, 0, 100, o(0), 5, slow.speed)
    expect(fast.speed as number).toBeGreaterThan(slow.speed as number)
  })

  it('has nothing to do without speeds', () => {
    expect(readJoystick(80, 0, 100, o(0), 0).directions).toEqual([])
  })
})
