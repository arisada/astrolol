import type { PairedSerialDevice } from '@/api/types'

export interface DiscoveredDevice {
  mac: string
  name: string
  rssi: number | null
  paired: boolean
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail ?? `HTTP ${res.status}`)
  }
  if (res.status === 204) return undefined as T
  return res.json()
}

export const scan = (timeoutSeconds = 8) =>
  request<DiscoveredDevice[]>(`/plugins/bluetooth_serial/scan?timeout=${timeoutSeconds}`)

export const pair = (mac: string, pin: string, name?: string) =>
  request<PairedSerialDevice>('/plugins/bluetooth_serial/pair', {
    method: 'POST',
    body: JSON.stringify({ mac, pin: pin || null, name: name || null }),
  })

export const rename = (deviceId: string, name: string) =>
  request<PairedSerialDevice>(`/plugins/bluetooth_serial/paired/${encodeURIComponent(deviceId)}`, {
    method: 'PATCH',
    body: JSON.stringify({ name }),
  })

export const forget = (deviceId: string) =>
  request<void>(`/plugins/bluetooth_serial/paired/${encodeURIComponent(deviceId)}`, { method: 'DELETE' })
