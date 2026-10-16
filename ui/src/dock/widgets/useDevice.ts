import { useStore } from '@/store'
import type { DeviceKind } from '@/api/types'

/** The connected device a widget shows: the one it was pinned for, else the first of its kind.
 *  undefined when that device is not connected. */
export function useDevice(kind: DeviceKind, deviceId?: string): string | undefined {
  return useStore((s) => {
    const same = s.connectedDevices.filter((d) => d.kind === kind)
    return (deviceId ? same.find((d) => d.device_id === deviceId) : same[0])?.device_id
  })
}
