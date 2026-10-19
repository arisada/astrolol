// Helpers for the Tonight list.

import type { TonightItem } from './api'

/** Whether an object is already above the minimum altitude, and when that starts or stops. */
export function timing(item: TonightItem): { state: 'up' | 'rises'; rises: string | null; sets: string | null } {
  return { state: item.rise_time ? 'rises' : 'up', rises: item.rise_time, sets: item.set_time }
}

/** Index of the first object too close to the Moon (they come last), or -1 when none is. */
export function firstNearMoon(items: readonly TonightItem[]): number {
  return items.findIndex((i) => i.near_moon)
}

/** "3.4" for a magnitude; null when unknown. */
export function fmtMag(mag: number | null): string | null {
  return mag === null ? null : mag.toFixed(1)
}

/** Apparent size: arcminutes below one degree, degrees above; null when unknown. */
export function fmtSize(arcmin: number | null): string | null {
  if (arcmin === null || arcmin <= 0) return null
  if (arcmin >= 120) return `${(arcmin / 60).toFixed(1)}°`
  return arcmin >= 10 ? `${Math.round(arcmin)}′` : `${arcmin.toFixed(1)}′`
}
