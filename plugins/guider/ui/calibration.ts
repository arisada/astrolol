// Turns the calibration matrix into the numbers a person reads.
import type { Calibration } from './api'

export interface CalibrationSummary {
  raRate: number // pixels per second of guide pulse
  decRate: number
  raAngle: number // degrees, direction a West pulse moves the star on the sensor
  decAngle: number // degrees, direction a North pulse moves the star
  orthogonality: number // degrees between the two axes (90 is ideal)
  backlashMs: number
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
  }
}
