import type {
  NetworkStatus,
  SystemSettings,
  SystemStatus,
  SudoSetup,
  WifiNetwork,
} from '@/api/types'

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

export const getSystemStatus = () =>
  request<SystemStatus>('/plugins/system/status')

export const getNetworkStatus = () =>
  request<NetworkStatus>('/plugins/system/network')

export const scanWifi = () =>
  request<WifiNetwork[]>('/plugins/system/network/scan')

export const connectWifi = (ssid: string, password: string) =>
  request<{ status: string; ssid: string }>('/plugins/system/network/connect', {
    method: 'POST',
    body: JSON.stringify({ ssid, password }),
  })

export const disconnectWifi = () =>
  request<{ status: string }>('/plugins/system/network/disconnect', { method: 'POST' })

export const startHotspot = (ssid?: string, password?: string) =>
  request<{ status: string; ssid: string }>('/plugins/system/network/hotspot/start', {
    method: 'POST',
    body: JSON.stringify({ ssid, password }),
  })

export const stopHotspot = () =>
  request<{ status: string }>('/plugins/system/network/hotspot/stop', { method: 'POST' })

export const getSettings = () =>
  request<SystemSettings>('/plugins/system/settings')

export const putSettings = (s: SystemSettings) =>
  request<SystemSettings>('/plugins/system/settings', {
    method: 'PUT',
    body: JSON.stringify(s),
  })

export const getSudoSetup = () =>
  request<SudoSetup>('/plugins/system/sudo')

export const reboot = () =>
  request<{ status: string }>('/plugins/system/reboot', { method: 'POST' })

export const shutdown = () =>
  request<{ status: string }>('/plugins/system/shutdown', { method: 'POST' })

export const restartApp = () =>
  request<{ status: string }>('/plugins/system/restart', { method: 'POST' })
