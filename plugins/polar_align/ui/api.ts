import type { ReticleCalibration, ReticleState, WizardRequest, WizardRun } from '@/api/types'

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

// ── Part 1: polar scope reticle ─────────────────────────────────────────────────

export const getReticle = (mountNodeId?: string, mountId?: string) => {
  const params = new URLSearchParams()
  if (mountNodeId) params.set('mount_node_id', mountNodeId)
  if (mountId) params.set('mount_id', mountId)
  const qs = params.toString()
  return request<ReticleState>(`/plugins/polar_align/reticle${qs ? `?${qs}` : ''}`)
}

export const calibrateReticle = (mountNodeId: string, mountId?: string) =>
  request<ReticleCalibration>('/plugins/polar_align/reticle/calibrate', {
    method: 'POST',
    body: JSON.stringify({ mount_node_id: mountNodeId, mount_id: mountId ?? null }),
  })

export const deleteReticleCalibration = (mountNodeId: string) =>
  request<void>(`/plugins/polar_align/reticle/calibration/${encodeURIComponent(mountNodeId)}`, {
    method: 'DELETE',
  })
