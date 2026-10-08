// Fetch helpers mirroring plugins/guider/api.py.
import type { GuiderStatus, GuidingHealth, GuidingStats, SettleParams } from '@/api/types'
import type { GuideSample } from '@/utils/guiding'

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...options })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(typeof body.detail === 'string' ? body.detail : `HTTP ${res.status}`)
  }
  if (res.status === 204) return undefined as T
  return res.json()
}

const BASE = '/plugins/guider'
const post = <T>(path: string, body?: unknown) =>
  request<T>(BASE + path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })

export type GuideOutput = 'camera' | 'mount'

export interface GuiderSettings {
  guide_output: GuideOutput
  camera_id: string | null
  mount_id: string | null
  exposure: number
  gain: number | null
  pixel_scale: number | null
  star_count: number
  calibration_steps: number
  lost_timeout_s: number
}

export interface Calibration {
  ra_x: number
  ra_y: number
  dec_x: number
  dec_y: number
  dec_backlash_ms: number
}

export interface DarkInfo {
  exposure: number
  gain: number | null
  binning: number
  region: [number, number, number, number]
  frames: number
  hot_pixels: number
}

export interface GuiderReport {
  status: GuiderStatus
  health: GuidingHealth
  last_minute: GuidingStats
  calibration: Calibration | null
  darks: DarkInfo[]
}

// What the plugin keeps in the store (pluginStates['guider']).
export interface GuiderPluginState {
  guiding: boolean | null // null until the guider has said anything
  reason: string | null
  steps: GuideSample[]
}

export const DEFAULT_GUIDER_STATE: GuiderPluginState = { guiding: null, reason: null, steps: [] }
export const MAX_STEPS = 500

export type StarKind = 'primary' | 'companion' | 'candidate' | 'lost'

export interface OverlayStar {
  x: number
  y: number
  kind: StarKind
  snr: number | null
  fwhm: number | null
  half: number
}

export interface ViewInfo {
  mode: 'idle' | 'preview' | 'guiding'
  version: number
  width: number
  height: number
  origin: [number, number]
  stars: OverlayStar[]
  locks: [number, number][]
}

export const frameUrl = (version: number) => `${BASE}/frame.jpg?v=${version}`
export const getView = () => request<ViewInfo>(`${BASE}/view`)
export const startPreview = () => post<void>('/preview')
export const stopPreview = () => request<void>(`${BASE}/preview`, { method: 'DELETE' })

export const getStatus = () => request<GuiderReport>(`${BASE}/status`)
export const guide = (recalibrate: boolean, settle?: SettleParams) =>
  post<void>('/guide', { recalibrate, ...(settle ? { settle } : {}) })
export const stop = () => post<void>('/stop')
export const pause = () => post<void>('/pause')
export const resume = () => post<void>('/resume')
export const dither = (pixels = 3) => post<void>('/dither', { pixels })
export const clearCalibration = () => request<void>(`${BASE}/calibration`, { method: 'DELETE' })
export const captureDark = (count: number) => post<DarkInfo>('/darks', { count })
export const clearDarks = () => request<void>(`${BASE}/darks`, { method: 'DELETE' })
export const getSettings = () => request<GuiderSettings>(`${BASE}/settings`)
export const putSettings = (s: GuiderSettings) =>
  request<GuiderSettings>(`${BASE}/settings`, { method: 'PUT', body: JSON.stringify(s) })
