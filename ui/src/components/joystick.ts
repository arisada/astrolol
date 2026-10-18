/**
 * Maths of the nudge joystick, free of React so it can be tested.
 *
 * The thumb's displacement from where it first touched (x right, y down, in pixels) becomes a
 * sky direction and a speed. The orientation says how the eyepiece shows the sky: rotated
 * clockwise by 0/90/180/270° and/or mirrored (a diagonal mirrors the image).
 */

export type Direction = 'N' | 'S' | 'E' | 'W'
export type Rotation = 0 | 90 | 180 | 270
export interface Orientation { rotation: Rotation; mirror: boolean }

export const NORTH_UP: Orientation = { rotation: 0, mirror: false }
export const ROTATIONS: readonly Rotation[] = [0, 90, 180, 270]

/** Below this share of the full-speed radius nothing moves. */
export const DEAD_ZONE = 0.12
/** A secondary axis weaker than this share of the main one is dropped (no accidental diagonals). */
export const AXIS_SNAP = 0.4
/** > 1 spends more of the travel on the slow speeds, where fine centring happens. */
export const SPEED_CURVE = 1.8
/** How far past a speed boundary (in speed steps) the thumb must go to change speed. */
export const HYSTERESIS = 0.15

/** The sky vector (x east, y south, as the pad draws it with North up) for a thumb displacement. */
export function toSky(dx: number, dy: number, o: Orientation): { x: number; y: number } {
  // The eyepiece shows the sky rotated clockwise by `rotation`; undo it, then undo the mirror.
  const a = (-o.rotation * Math.PI) / 180
  const x = Math.round((dx * Math.cos(a) - dy * Math.sin(a)) * 1e9) / 1e9
  const y = Math.round((dx * Math.sin(a) + dy * Math.cos(a)) * 1e9) / 1e9
  return { x: o.mirror ? -x : x, y }
}

/** The sky direction at the top, right, bottom and left of the pad, for labelling it. */
export function edgeDirections(o: Orientation): { top: Direction; right: Direction; bottom: Direction; left: Direction } {
  const dir = (dx: number, dy: number) => directionsOf(toSky(dx, dy, o).x, toSky(dx, dy, o).y, 0)[0]
  return { top: dir(0, -1), right: dir(1, 0), bottom: dir(0, 1), left: dir(-1, 0) }
}

/** Directions to move for a sky vector; the weaker axis is dropped when much weaker than the other. */
export function directionsOf(x: number, y: number, snap = AXIS_SNAP): Direction[] {
  const major = Math.max(Math.abs(x), Math.abs(y))
  if (major === 0) return []
  const out: Direction[] = []
  if (Math.abs(x) > 0 && Math.abs(x) >= snap * major) out.push(x > 0 ? 'E' : 'W')
  if (Math.abs(y) > 0 && Math.abs(y) >= snap * major) out.push(y > 0 ? 'S' : 'N')
  return out
}

export interface JoystickReading {
  directions: Direction[]
  /** Index into the speed list, slowest first; null while inside the dead zone. */
  speed: number | null
}

/**
 * @param radius      displacement, in pixels, that means full speed
 * @param speedCount  number of speeds, slowest first; the last is the fastest allowed
 * @param previous    the speed index last returned, to keep it steady near a boundary
 */
export function readJoystick(
  dx: number, dy: number, radius: number, o: Orientation, speedCount: number, previous: number | null = null,
): JoystickReading {
  const share = Math.min(1, Math.hypot(dx, dy) / radius)
  if (share < DEAD_ZONE || speedCount < 1) return { directions: [], speed: null }
  const sky = toSky(dx, dy, o)
  const travel = ((share - DEAD_ZONE) / (1 - DEAD_ZONE)) ** SPEED_CURVE * speedCount
  let speed = Math.min(speedCount - 1, Math.floor(travel))
  if (previous !== null && previous < speedCount && speed !== previous) {
    // Stay on the previous speed until the thumb is clearly into the next one.
    if (travel > previous - HYSTERESIS && travel < previous + 1 + HYSTERESIS) speed = previous
  }
  return { directions: directionsOf(sky.x, sky.y), speed }
}
