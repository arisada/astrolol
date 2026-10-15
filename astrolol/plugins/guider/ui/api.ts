// Fetch helpers mirroring plugins/guider/api.py.
import type { FrameStats, GuiderStatus, OverlayStar, GuidingHealth, GuidingStats, SettleParams } from '@/api/types'
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

export type DecMode = 'auto' | 'north' | 'south' | 'off'
export type FlipDec = 'auto' | 'yes' | 'no'

export interface GuiderSettings {
  guide_output: GuideOutput
  camera_id: string | null
  mount_id: string | null
  exposure: number
  gain: number | null
  binning: number
  pixel_scale: number | null
  star_count: number
  dec_backlash_compensation: boolean
  dec_resist_reversals: boolean
  calibration_steps: number
  calibration_travel_px: number
  flip_dec_after_meridian_flip: FlipDec
  lost_timeout_s: number
  ra_aggressiveness: number
  ra_hysteresis: number
  dec_aggressiveness: number
  min_move_px: number | null // null: from the pixel scale
  max_pulse_ms: number
  min_pulse_ms: number
  dec_mode: DecMode
  predict_drift: boolean
  predict_periodic_error: boolean
  worm_period_s: number | null
}

export type CalibrationPhase = 'drift' | 'probe' | 'west' | 'east' | 'north' | 'south'

export interface CalibrationPoint {
  phase: CalibrationPhase
  step: number // 0 is the position before the phase's first pulse
  pulse_ms: number
  x: number
  y: number
  t: number // seconds since the calibration started
  used: boolean // false: measured but left out of the fit
}

export type CalibrationIssue =
  | 'noisy' | 'short_travel' | 'not_perpendicular' | 'ra_asymmetric' | 'dec_asymmetric'
  | 'rate_ratio' | 'high_dec' | 'dec_backlash_large' | 'ra_backlash_large'

export interface CalibrationQuality {
  residual_px: number
  noise_px: number
  ra_travel_px: number
  dec_travel_px: number
  axes_angle_deg: number
  ra_asymmetry: number | null
  dec_asymmetry: number | null
  rate_ratio: number
  expected_ratio: number | null // cos(declination) when known
  issues: CalibrationIssue[]
}

export interface Calibration {
  ra_x: number
  ra_y: number
  dec_x: number
  dec_y: number
  dec_backlash_ms: number
  ra_backlash_ms: number
  drift_x: number
  drift_y: number
  trace: CalibrationPoint[]
  dec: number | null
  pier_side: string | null
  created: number | null // Unix time
  quality: CalibrationQuality | null
  flip_dec: boolean | null
}

export interface CalibrationAttempt {
  running: boolean
  phase: string
  trace: CalibrationPoint[]
  error: string | null
}

export interface Prediction {
  drift_ra: number // per second, arcsec (pixels without a pixel scale)
  drift_dec: number
  pe_period_s: number | null
  pe_amplitude: number | null // peak to peak
}

export interface MountReport {
  dec: number | null
  pier_side: string | null
  slewing: boolean
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
  active_calibration: Calibration | null // as it applies where the mount points now
  calibration_attempt: CalibrationAttempt | null
  darks: DarkInfo[]
  dark_matches: boolean
  pixel_scale_source: 'settings' | 'optics' | null
  last_error: string | null
  mount: MountReport | null
  preferred_star: [number, number] | null
  prediction: Prediction | null
}

// What the plugin keeps in the store (pluginStates['guider']).
export interface GuiderPluginState {
  guiding: boolean | null // null until the guider has said anything
  reason: string | null
  steps: GuideSample[]
  snr: number | null // the guide star's, in the latest frame
  stars: number | null // guide stars found in the latest frame
}

export const DEFAULT_GUIDER_STATE: GuiderPluginState = { guiding: null, reason: null, steps: [], snr: null, stars: null }
export const MAX_STEPS = 500

export type { FrameStats, OverlayStar, StarKind } from '@/api/types'

export interface ViewInfo {
  mode: 'idle' | 'preview' | 'calibrating' | 'guiding'
  version: number
  width: number
  height: number
  origin: [number, number]
  stars: OverlayStar[]
  locks: [number, number][]
  pixel_scale: number | null
  stats: FrameStats | null
}

export const frameUrl = (version: number) => `${BASE}/frame.jpg?v=${version}`
export const getView = () => request<ViewInfo>(`${BASE}/view`)
export const startPreview = () => post<void>('/preview')
export const stopPreview = () => request<void>(`${BASE}/preview`, { method: 'DELETE' })
export const selectStar = (x: number, y: number) => post<void>('/star', { x, y })
export const clearStar = () => request<void>(`${BASE}/star`, { method: 'DELETE' })

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
