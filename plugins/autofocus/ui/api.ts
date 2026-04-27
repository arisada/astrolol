import type { AutofocusConfig, AutofocusRun, AutofocusSettings } from '@/api/types'

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

export const getSettings = () =>
  request<AutofocusSettings>('/plugins/autofocus/settings')

export const putSettings = (s: AutofocusSettings) =>
  request<AutofocusSettings>('/plugins/autofocus/settings', {
    method: 'PUT',
    body: JSON.stringify(s),
  })

export const start = (config: AutofocusConfig) =>
  request<AutofocusRun>('/plugins/autofocus/start', {
    method: 'POST',
    body: JSON.stringify(config),
  })

export const abort = () =>
  request<void>('/plugins/autofocus/abort', { method: 'POST' })

export const run = () =>
  request<AutofocusRun>('/plugins/autofocus/run')

export const previewUrl = (step: number) =>
  `/plugins/autofocus/run/preview/${step}`
