// The long exposures in progress, kept in the plugin's slice of the store (device id -> progress).
import type { AstrolollEvent } from '@/api/types'

export interface StackProgress {
  subsDone: number
  subsTotal: number
  exposureDone: number
  exposureTotal: number
}

export type StackProgressState = Record<string, StackProgress>

/** The state after a progress event: the device's entry replaced or removed, null once none is left. */
export function applyProgress(
  event: Extract<AstrolollEvent, { type: 'stacked_camera.progress' }>,
  current: StackProgressState | null | undefined,
): StackProgressState | null {
  const next = { ...(current ?? {}) }
  if (event.active) {
    next[event.device_id] = {
      subsDone: event.subs_done,
      subsTotal: event.subs_total,
      exposureDone: event.exposure_done,
      exposureTotal: event.exposure_total,
    }
  } else {
    delete next[event.device_id]
  }
  return Object.keys(next).length > 0 ? next : null
}
