import type { Phd2Settings, Phd2Status } from '@/api/types'

// Plugin-local state shape (stored in useStore.pluginStates['phd2'])
export interface GuidePoint {
  frame: number
  ra: number
  dec: number
  ts: string
}

export interface Phd2PluginState {
  status: Phd2Status | null
  guidePoints: GuidePoint[]
}

export const DEFAULT_PHD2_STATE: Phd2PluginState = { status: null, guidePoints: [] }
export const MAX_GUIDE_STEPS = 500

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

export const connect    = () => request<void>('/plugins/phd2/connect',    { method: 'POST' })
export const disconnect = () => request<void>('/plugins/phd2/disconnect', { method: 'POST' })
export const status     = () => request<Phd2Status>('/plugins/phd2/status')
export const guide      = (settlePixels?: number, settleTime?: number, settleTimeout?: number, recalibrate?: boolean) =>
  request<void>('/plugins/phd2/guide', {
    method: 'POST',
    body: JSON.stringify({
      settle: { pixels: settlePixels ?? 1.5, time: settleTime ?? 10, timeout: settleTimeout ?? 60 },
      recalibrate: recalibrate ?? false,
    }),
  })
export const stop       = () => request<void>('/plugins/phd2/stop',   { method: 'POST' })
export const dither     = (pixels?: number, raOnly?: boolean) =>
  request<void>('/plugins/phd2/dither', {
    method: 'POST',
    body: JSON.stringify({ pixels: pixels ?? 5.0, ra_only: raOnly ?? false }),
  })
export const pause      = () => request<void>('/plugins/phd2/pause',  { method: 'POST' })
export const resume     = () => request<void>('/plugins/phd2/resume', { method: 'POST' })
export const setDebug   = (enabled: boolean) =>
  request<void>('/plugins/phd2/debug', { method: 'POST', body: JSON.stringify({ enabled }) })
export const getSettings = () => request<Phd2Settings>('/plugins/phd2/settings')
export const putSettings = (s: Phd2Settings) =>
  request<Phd2Settings>('/plugins/phd2/settings', { method: 'PUT', body: JSON.stringify(s) })
