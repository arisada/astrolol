/**
 * Global background polling for device statuses that aren't fully covered by
 * WebSocket events (mount coordinates, focuser position, filter-wheel state,
 * camera cooler temperature).  Runs once at the Layout level so every page
 * benefits without duplicating HTTP calls.
 */
import { useEffect } from 'react'
import { api } from '@/api/client'
import { useStore } from '@/store'

const POLL_INTERVAL_MS = 5_000

export function useStatusPolling() {
  // Read connected devices reactively so the effect re-runs when devices change.
  const connectedDevices = useStore((s) => s.connectedDevices)

  useEffect(() => {
    let cancelled = false

    const poll = async () => {
      if (cancelled) return
      const { setMountStatus, setFocuserStatus, setFilterWheelStatus, setCameraStatus } =
        useStore.getState()

      const mounts       = connectedDevices.filter((d) => d.kind === 'mount'        && d.state === 'connected')
      const focusers     = connectedDevices.filter((d) => d.kind === 'focuser'      && d.state === 'connected')
      const filterWheels = connectedDevices.filter((d) => d.kind === 'filter_wheel' && d.state === 'connected')
      const cameras      = connectedDevices.filter((d) => d.kind === 'camera'       && d.state === 'connected')

      await Promise.allSettled([
        ...mounts.map((d) =>
          api.mount.status(d.device_id).then((s) => { if (!cancelled) setMountStatus(d.device_id, s) }),
        ),
        ...focusers.map((d) =>
          api.focuser.status(d.device_id).then((s) => { if (!cancelled) setFocuserStatus(d.device_id, s) }),
        ),
        ...filterWheels.map((d) =>
          api.filterWheel.status(d.device_id).then((s) => { if (!cancelled) setFilterWheelStatus(d.device_id, s) }),
        ),
        ...cameras.map((d) =>
          api.imager.cameraStatus(d.device_id).then((s) => { if (!cancelled) setCameraStatus(d.device_id, s) }),
        ),
      ])
    }

    poll() // immediate first fetch
    const id = setInterval(poll, POLL_INTERVAL_MS)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [connectedDevices])
}
