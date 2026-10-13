import { useEffect, useState } from 'react'
import { api } from '@/api/client'
import type { ConnectedDevice, DeviceConfig } from '@/api/types'

/** The connection config of each connected device, by device id: tells which inventory item a device is. */
export function useDeviceConfigs(devices: ConnectedDevice[]): Record<string, DeviceConfig> {
  const [configs, setConfigs] = useState<Record<string, DeviceConfig>>({})
  const key = devices.map((d) => d.device_id).sort().join(',')

  useEffect(() => {
    let cancelled = false
    Promise.all(devices.map((d) =>
      api.devices.getConfig(d.device_id)
        .then((c) => [d.device_id, c] as const)
        .catch(() => null),
    )).then((entries) => {
      if (cancelled) return
      setConfigs(Object.fromEntries(entries.filter((e) => e !== null)))
    })
    return () => { cancelled = true }
  }, [key]) // eslint-disable-line react-hooks/exhaustive-deps

  return configs
}
