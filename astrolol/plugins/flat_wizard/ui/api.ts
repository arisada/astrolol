import type { FlatWizardConfig, FlatWizardRun } from '@/api/types'

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

export const start = (config: FlatWizardConfig) =>
  request<FlatWizardRun>('/plugins/flat_wizard/start', {
    method: 'POST',
    body: JSON.stringify(config),
  })

export const abort = () =>
  request<void>('/plugins/flat_wizard/abort', { method: 'POST' })

export const run = () =>
  request<FlatWizardRun>('/plugins/flat_wizard/run')
