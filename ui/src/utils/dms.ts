// Degrees/minutes/seconds (and hours/minutes/seconds) entry logic, kept free of React so it can be tested.
//
// An angle is held as a whole number of "ticks" (0.1 arc-second, or 0.1 second of time) plus a sign,
// so stepping and carrying are exact integer arithmetic: 59.9" + 0.1" is 1' 00.0", not 59.99999".
// Stepping a field carries into the next one (60' -> +1°); latitude/longitude are clamped to their
// range and right ascension wraps at 24 h. Invalid values cannot be produced.

export type DmsMode = 'lat' | 'lon' | 'ra'
export type DmsField = 'deg' | 'min' | 'sec'

export interface DmsParts {
  negative: boolean
  deg: number
  min: number
  /** Seconds, one decimal. */
  sec: number
}

const TICKS_PER_SEC = 10
const TICKS_PER_MIN = 60 * TICKS_PER_SEC
const TICKS_PER_DEG = 60 * TICKS_PER_MIN

const FIELD_TICKS: Record<DmsField, number> = { deg: TICKS_PER_DEG, min: TICKS_PER_MIN, sec: TICKS_PER_SEC }

/** Largest magnitude, in degrees (hours for RA). */
export const MAX_DEG: Record<DmsMode, number> = { lat: 90, lon: 180, ra: 24 }

const maxTicks = (mode: DmsMode) => MAX_DEG[mode] * TICKS_PER_DEG

function partsFromTicks(ticks: number, negative: boolean): DmsParts {
  const deg = Math.floor(ticks / TICKS_PER_DEG)
  const rest = ticks - deg * TICKS_PER_DEG
  const min = Math.floor(rest / TICKS_PER_MIN)
  const sec = (rest - min * TICKS_PER_MIN) / TICKS_PER_SEC
  return { negative: negative && ticks !== 0, deg, min, sec }
}

const ticksOf = (p: DmsParts) =>
  Math.round(p.deg * TICKS_PER_DEG + p.min * TICKS_PER_MIN + p.sec * TICKS_PER_SEC)

/** Split a decimal value (degrees, or hours for RA) into parts, rounded to 0.1". */
export function toParts(value: number): DmsParts {
  const t = Math.round(Math.abs(value) * TICKS_PER_DEG)
  return { ...partsFromTicks(t, value < 0), negative: value < 0 }
}

/**
 * Settle a (possibly out-of-range) set of parts: carry overflowing fields, clamp lat/lon to their
 * range, wrap RA into [0, 24 h). The sign is kept when the value is zero so "S 0° 30'" can be typed.
 */
export function normalise(p: DmsParts, mode: DmsMode): DmsParts {
  const raw = Math.max(0, ticksOf(p))
  if (mode === 'ra') {
    const wrapped = ((raw % maxTicks('ra')) + maxTicks('ra')) % maxTicks('ra')
    return { ...partsFromTicks(wrapped, false), negative: false }
  }
  const t = Math.min(raw, maxTicks(mode))
  return { ...partsFromTicks(t, p.negative), negative: p.negative }
}

/** Decimal value (degrees, or hours for RA) of a set of parts, after normalising. */
export function fromParts(p: DmsParts, mode: DmsMode): number {
  const n = normalise(p, mode)
  const v = ticksOf(n) / TICKS_PER_DEG
  return n.negative ? -v : v
}

/** One step up or down on a field; carries and clamps/wraps like normalise(). */
export function stepParts(p: DmsParts, field: DmsField, dir: 1 | -1, mode: DmsMode): DmsParts {
  const n = normalise(p, mode)
  const signed = (n.negative ? -1 : 1) * ticksOf(n) + dir * FIELD_TICKS[field]
  if (mode === 'ra') {
    const m = maxTicks('ra')
    return partsFromTicks(((signed % m) + m) % m, false)
  }
  const clamped = Math.max(-maxTicks(mode), Math.min(maxTicks(mode), signed))
  // Crossing zero flips the sign; sitting exactly at zero keeps the sign it had.
  const negative = clamped === 0 ? n.negative : clamped < 0
  return partsFromTicks(Math.abs(clamped), negative)
}

/** Flip N/S (E/W). Ignored for RA. */
export function flipSign(p: DmsParts, mode: DmsMode): DmsParts {
  return mode === 'ra' ? p : { ...p, negative: !p.negative }
}

/** Parse what the user typed into one field; empty or invalid text counts as 0. */
export function parseField(text: string, field: DmsField): number {
  const n = field === 'sec' ? parseFloat(text) : parseInt(text, 10)
  return Number.isFinite(n) && n >= 0 ? (field === 'sec' ? Math.round(n * 10) / 10 : n) : 0
}

export const pad = (n: number, width = 2) => String(n).padStart(width, '0')
export const fmtSec = (s: number) => s.toFixed(1).padStart(4, '0')
