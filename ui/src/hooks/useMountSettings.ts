import { useCallback, useEffect } from 'react'
import { create } from 'zustand'
import { api } from '@/api/client'
import type { MountDeviceSettings } from '@/api/types'

export const DEFAULT_NUDGE_RATE = '16x'

export const DEFAULT_MOUNT_SETTINGS: MountDeviceSettings = {
  auto_park_enabled: false,
  auto_park_time: null,
  auto_flip_enabled: false,
  auto_flip_ha_hours: 1.0,
  meridian_limit_deg: 20,
  horizon_min_alt_deg: 0,
  horizon_action: 'stop_tracking',
  nudge_rate: DEFAULT_NUDGE_RATE,
}

interface State { byDevice: Record<string, MountDeviceSettings> }

// One copy per mount, shared by every view of it (the Mount page and the dock's nudge widget), so
// a save from one never overwrites a field the other just changed with a stale copy.
const useStore = create<State>(() => ({ byDevice: {} }))

/** A mount's saved settings and a function that saves a changed copy. */
export function useMountSettings(deviceId: string): [MountDeviceSettings, (next: MountDeviceSettings) => void] {
  const settings = useStore((s) => s.byDevice[deviceId]) ?? DEFAULT_MOUNT_SETTINGS
  useEffect(() => {
    api.mount.getSettings(deviceId)
      .then((s) => useStore.setState((st) => ({ byDevice: { ...st.byDevice, [deviceId]: s } })))
      .catch(() => { /* keep the defaults */ })
  }, [deviceId])
  const save = useCallback((next: MountDeviceSettings) => {
    useStore.setState((st) => ({ byDevice: { ...st.byDevice, [deviceId]: next } }))
    api.mount.putSettings(deviceId, next).catch(() => {})
  }, [deviceId])
  return [settings, save]
}
