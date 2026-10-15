import type { AutoRefreshRequest, ReticleState, StarViewInfo, StarViewRequest, WizardRequest, WizardRun } from '@/api/types'

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

// ── Part 2: plate-solve wizard ──────────────────────────────────────────────────

export const startWizard = (req: WizardRequest) =>
  request<WizardRun>('/plugins/polar_align/wizard', { method: 'POST', body: JSON.stringify(req) })

export const getWizard = () => request<WizardRun>('/plugins/polar_align/wizard')

export const recheckWizard = () =>
  request<WizardRun>('/plugins/polar_align/wizard/recheck', { method: 'POST' })

export const cancelWizard = () =>
  request<void>('/plugins/polar_align/wizard', { method: 'DELETE' })

export const startAutoRefresh = (req: AutoRefreshRequest) =>
  request<WizardRun>('/plugins/polar_align/wizard/auto_refresh', {
    method: 'POST', body: JSON.stringify(req),
  })

export const stopAutoRefresh = () =>
  request<void>('/plugins/polar_align/wizard/auto_refresh', { method: 'DELETE' })

// ── Live star view ──────────────────────────────────────────────────────────────

export const startStarView = (req: StarViewRequest) =>
  request<StarViewInfo>('/plugins/polar_align/wizard/star_view', { method: 'POST', body: JSON.stringify(req) })

export const getStarView = () => request<StarViewInfo>('/plugins/polar_align/wizard/star_view')

export const stopStarView = () =>
  request<void>('/plugins/polar_align/wizard/star_view', { method: 'DELETE' })

export const starViewFrameUrl = (version: number) => `/plugins/polar_align/wizard/star_view/frame.jpg?v=${version}`

// ── Part 1: polar scope reticle ─────────────────────────────────────────────────

export const getReticle = () => request<ReticleState>('/plugins/polar_align/reticle')
