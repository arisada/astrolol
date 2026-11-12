// Fetch helpers mirroring plugins/stacked_camera/api.py.

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...options })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(typeof body.detail === 'string' ? body.detail : `HTTP ${res.status}`)
  }
  if (res.status === 204) return undefined as T
  return res.json()
}

const BASE = '/plugins/stacked_camera'

export interface Attached {
  stacked: string
  fast: string
}

export interface CameraChoice {
  device_id: string
  attached: Attached | null
}

export interface SourceStatus {
  source_id: string
  running: boolean
  sub_exposure: number
  gain: number | null
  binning: number
  frames: number
  dropped: number
  duty: number | null
  error: string | null
}

export interface StackedStatus {
  cameras: CameraChoice[]
  sources: SourceStatus[]
}

export interface StackedCameraSettings {
  sub_exposure: number
}

export const getStatus = () => request<StackedStatus>(`${BASE}/status`)
export const getSettings = () => request<StackedCameraSettings>(`${BASE}/settings`)
export const putSettings = (s: StackedCameraSettings) =>
  request<StackedCameraSettings>(`${BASE}/settings`, { method: 'PUT', body: JSON.stringify(s) })
export const attach = (sourceId: string) =>
  request<Attached>(`${BASE}/attach`, { method: 'POST', body: JSON.stringify({ source_id: sourceId }) })
export const detach = (sourceId: string) =>
  request<void>(`${BASE}/detach`, { method: 'POST', body: JSON.stringify({ source_id: sourceId }) })
