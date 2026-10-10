// Fetch helpers mirroring plugins/guide_simulator/api.py.
import type { GuiderStatus, GuidingHealth, GuidingStats, SettleParams } from '@/api/types'

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...options })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(typeof body.detail === 'string' ? body.detail : `HTTP ${res.status}`)
  }
  if (res.status === 204) return undefined as T
  return res.json()
}

const BASE = '/plugins/guide_simulator'
const post = <T>(path: string, body?: unknown) =>
  request<T>(BASE + path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })

export interface SimFaults {
  star_lost: boolean
  star_back_in_s: number | null
  settle_failures_left: number
}

export interface SimReport {
  status: GuiderStatus
  health: GuidingHealth
  last_minute: GuidingStats
  faults: SimFaults
}

export interface GuideSimSettings {
  connected_at_startup: boolean
  rms_arcsec: number
  pixel_scale: number
  step_interval_s: number
  settle_extra_s: number
  lose_star_on_slew: boolean
  time_scale: number
}

export const getStatus = () => request<SimReport>(`${BASE}/status`)
export const connect = () => post<void>('/connect')
export const disconnect = () => post<void>('/disconnect')
export const guide = (settle?: SettleParams) => post<void>('/guide', settle)
export const stop = () => post<void>('/stop')
export const dither = (pixels = 3) => post<void>('/dither', { pixels })
export const loseStar = (durationS: number | null) => post<void>('/faults/star_loss', { duration_s: durationS })
export const stopGuidingFault = () => post<void>('/faults/stop_guiding')
export const failSettles = (count: number) => post<void>('/faults/settle_failures', { count })
export const clearFaults = () => post<void>('/faults/clear')
export const getSettings = () => request<GuideSimSettings>(`${BASE}/settings`)
export const putSettings = (s: GuideSimSettings) =>
  request<GuideSimSettings>(`${BASE}/settings`, { method: 'PUT', body: JSON.stringify(s) })
