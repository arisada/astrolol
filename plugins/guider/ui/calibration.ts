// Turns the calibration matrix into the numbers a person reads.
import type { Calibration, CalibrationPoint } from './api'

export interface CalibrationSummary {
  raRate: number // pixels per second of guide pulse
  decRate: number
  raAngle: number // degrees, direction a West pulse moves the star on the sensor
  decAngle: number // degrees, direction a North pulse moves the star
  orthogonality: number // degrees between the two axes (90 is ideal)
  backlashMs: number
  raBacklashMs: number
  drift: number // pixels per second with no pulses
}

const deg = (rad: number) => (rad * 180) / Math.PI

export function summarizeCalibration(c: Calibration): CalibrationSummary {
  const ra = Math.hypot(c.ra_x, c.ra_y)
  const dec = Math.hypot(c.dec_x, c.dec_y)
  const cos = (c.ra_x * c.dec_x + c.ra_y * c.dec_y) / (ra * dec)
  return {
    raRate: ra * 1000,
    decRate: dec * 1000,
    raAngle: deg(Math.atan2(c.ra_y, c.ra_x)),
    decAngle: deg(Math.atan2(c.dec_y, c.dec_x)),
    orthogonality: deg(Math.acos(Math.max(-1, Math.min(1, cos)))),
    backlashMs: c.dec_backlash_ms,
    raBacklashMs: c.ra_backlash_ms,
    drift: Math.hypot(c.drift_x, c.drift_y),
  }
}

export interface TraceBounds {
  minX: number
  maxX: number
  minY: number
  maxY: number
}

/** The area holding every measured position, padded and made square so a move looks like it is:
 *  pixels are pixels in both directions. */
export function traceBounds(trace: CalibrationPoint[], padding = 0.12): TraceBounds {
  if (trace.length === 0) return { minX: -1, maxX: 1, minY: -1, maxY: 1 }
  const xs = trace.map((p) => p.x)
  const ys = trace.map((p) => p.y)
  const cx = (Math.min(...xs) + Math.max(...xs)) / 2
  const cy = (Math.min(...ys) + Math.max(...ys)) / 2
  const half = Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys), 1) / 2 * (1 + 2 * padding)
  return { minX: cx - half, maxX: cx + half, minY: cy - half, maxY: cy + half }
}

/** The points of one phase, in the order they were measured. */
export const phasePoints = (trace: CalibrationPoint[], phase: CalibrationPoint['phase']) =>
  trace.filter((p) => p.phase === phase).sort((a, b) => a.step - b.step)
