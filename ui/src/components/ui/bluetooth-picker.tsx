import { useEffect, useState } from 'react'
import { api } from '@/api/client'
import type { PairedSerialDevice } from '@/api/types'

/**
 * Lets any device's connection UI (e.g. eqmod) pick a paired Bluetooth serial
 * device by name, with no MAC address or RFCOMM channel in sight. Backed by
 * core's read-only `/devices/bluetooth/paired` list — pairing itself lives in
 * the bluetooth_serial plugin's own page, not here.
 */
export function BluetoothDevicePicker({
  value,
  onChange,
  disabled,
}: {
  value: string | null
  onChange: (deviceId: string | null) => void
  disabled?: boolean
}) {
  const [devices, setDevices] = useState<PairedSerialDevice[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.bluetooth
      .paired()
      .then(setDevices)
      .catch((e: Error) => setError(e.message))
  }, [])

  if (error) {
    return <p className="text-xs text-status-error">Could not load paired Bluetooth devices: {error}</p>
  }

  if (devices !== null && devices.length === 0) {
    return (
      <p className="text-xs text-slate-500">
        No paired Bluetooth devices yet — pair one from the{' '}
        <span className="font-mono">Bluetooth Serial</span> plugin page first.
      </p>
    )
  }

  return (
    <select
      value={value ?? ''}
      disabled={disabled || devices === null}
      onChange={(e) => onChange(e.target.value || null)}
      className="w-full rounded bg-surface-overlay border border-surface-border px-3 py-1.5 text-sm
        text-slate-200 focus:outline-none focus:ring-1 focus:ring-accent disabled:opacity-40"
    >
      <option value="">{devices === null ? 'Loading…' : 'Select a paired device…'}</option>
      {devices?.map((d) => (
        <option key={d.id} value={d.id}>
          {d.name}
        </option>
      ))}
    </select>
  )
}
