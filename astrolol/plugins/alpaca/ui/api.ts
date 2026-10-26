// Mirrors astrolol/plugins/alpaca/api.py (and the core POST /devices/connect it uses).

export interface AlpacaDeviceInfo {
  name: string
  device_type: string
  device_number: number
  unique_id: string
  /** astrolol's device kind; null when astrolol has no support for this type yet */
  kind: string | null
  adapter_key: string | null
}

export interface AlpacaServerInfo {
  host: string
  port: number
  name: string
  manufacturer: string
  version: string
  location: string
  devices: AlpacaDeviceInfo[]
}

export interface AddressError {
  address: string
  error: string
}

export interface DiscoverResponse {
  servers: AlpacaServerInfo[]
  errors: AddressError[]
}

export interface ConnectedAlpacaDevice {
  device_id: string
  kind: string
  adapter_key: string
  state: string
  host: string
  port: number
  device_number: number
}

export interface AlpacaSettings {
  addresses: string[]
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    const detail = body.detail
    throw new Error(typeof detail === 'string' ? detail : `HTTP ${res.status}`)
  }
  if (res.status === 204) return undefined as T
  return res.json()
}

export const discover = (addresses: string[] = []) =>
  request<DiscoverResponse>('/plugins/alpaca/discover', { method: 'POST', body: JSON.stringify({ addresses }) })
export const getConnected = () => request<ConnectedAlpacaDevice[]>('/plugins/alpaca/connected')
export const getSettings = () => request<AlpacaSettings>('/plugins/alpaca/settings')
export const putSettings = (s: AlpacaSettings) =>
  request<AlpacaSettings>('/plugins/alpaca/settings', { method: 'PUT', body: JSON.stringify(s) })

export const connectDevice = (server: AlpacaServerInfo, device: AlpacaDeviceInfo, deviceId: string) =>
  request<{ device_id: string }>('/devices/connect', {
    method: 'POST',
    body: JSON.stringify({
      device_id: deviceId,
      kind: device.kind,
      adapter_key: device.adapter_key,
      params: { host: server.host, port: server.port, device_number: device.device_number },
    }),
  })
