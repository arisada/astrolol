import type {
  HostnameInfo,
  NetworkStatus,
  SavedWifiConnection,
  StorageDisk,
  SystemSettings,
  SystemStatus,
  SudoSetup,
  TimeInfo,
  UsbDevice,
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

export const getUsbDevices = () =>
  request<UsbDevice[]>('/plugins/system/usb')

export const listSavedConnections = () =>
  request<SavedWifiConnection[]>('/plugins/system/network/saved')

export const deleteSavedConnection = (name: string) =>
  request<void>(`/plugins/system/network/saved/${encodeURIComponent(name)}`, { method: 'DELETE' })

export const getStorage = () =>
  request<StorageDisk[]>('/plugins/system/storage')

export const getTimeInfo = () =>
  request<TimeInfo>('/plugins/system/time')

export const listTimezones = () =>
  request<string[]>('/plugins/system/time/timezones')

export const setTimezone = (timezone: string) =>
  request<{ timezone: string }>('/plugins/system/time/timezone', {
    method: 'PUT',
    body: JSON.stringify({ timezone }),
  })

export const getHostname = () =>
  request<HostnameInfo>('/plugins/system/hostname')

export const setHostname = (hostname: string) =>
  request<HostnameInfo>('/plugins/system/hostname', {
    method: 'PUT',
    body: JSON.stringify({ hostname }),
  })

export const reboot = () =>
  request<{ status: string }>('/plugins/system/reboot', { method: 'POST' })

export const shutdown = () =>
  request<{ status: string }>('/plugins/system/shutdown', { method: 'POST' })

export const restartApp = () =>
  request<{ status: string }>('/plugins/system/restart', { method: 'POST' })
