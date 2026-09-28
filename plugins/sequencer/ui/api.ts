// Fetch helpers mirroring plugins/sequencer/api.py (plus the few other plugins' routes the
// task editor reads: object search and favorites).
import type {
  SequencerBoundary,
  SequencerPreflightReport,
  SequencerQueueEntry,
  SequencerSettings,
  SequencerStatus,
  SequencerTask,
} from '@/api/types'

export class ApiError extends Error {
  constructor(message: string, public status: number, public detail: unknown) {
    super(message)
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    const detail = body.detail
    const message =
      typeof detail === 'string' ? detail
      : Array.isArray(detail) ? detail.map((d: { loc?: unknown[]; msg?: string }) =>
          `${(d.loc ?? []).slice(1).join('.')}: ${d.msg ?? ''}`).join('; ')
      : detail && typeof detail.message === 'string' ? detail.message
      : `HTTP ${res.status}`
    throw new ApiError(message, res.status, detail)
  }
  if (res.status === 204) return undefined as T
  return res.json()
}

const BASE = '/plugins/sequencer'
const post = <T>(path: string, body?: unknown) =>
  request<T>(BASE + path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })

// ── Queue ──
export const getQueue = () => request<SequencerQueueEntry[]>(`${BASE}/queue`)
export const addTask = (task: SequencerTask) => post<SequencerQueueEntry>('/queue', task)
export const updateTask = (id: string, task: SequencerTask) =>
  request<SequencerQueueEntry>(`${BASE}/queue/${id}`, { method: 'PUT', body: JSON.stringify(task) })
export const removeTask = (id: string) => request<void>(`${BASE}/queue/${id}`, { method: 'DELETE' })
export const duplicateTask = (id: string) => post<SequencerQueueEntry>(`/queue/${id}/duplicate`)
export const resetProgress = (id: string) => post<SequencerQueueEntry>(`/queue/${id}/reset_progress`)
export const skipTask = (id: string) => post<SequencerQueueEntry>(`/queue/${id}/skip`)
export const unskipTask = (id: string) => post<SequencerQueueEntry>(`/queue/${id}/unskip`)
export const reorder = (order: string[]) => post<void>('/queue/reorder', { order })
export const clearQueue = (statuses: string[]) =>
  request<void>(`${BASE}/queue?${statuses.map((s) => `status=${s}`).join('&')}`, { method: 'DELETE' })

// ── Control ──
export const preflight = (taskIds?: string[]) =>
  post<SequencerPreflightReport>('/preflight', { task_ids: taskIds ?? null })
export const start = (opts: { from_task?: string; only?: string[] } = {}) =>
  post<{ status: string }>('/start', { ...opts, actor: 'user' })
export const pause = (when: SequencerBoundary) => post<void>(`/pause?when=${when}`)
export const resume = () => post<void>('/resume')
export const stop = (when: SequencerBoundary) => post<void>(`/stop?when=${when}`)
export const skipCurrent = (when: SequencerBoundary) => post<void>(`/skip_current?when=${when}`)
export const switchTo = (taskId: string, when: SequencerBoundary = 'frame') =>
  post<void>('/switch', { task_id: taskId, when, actor: 'user' })

// ── Status & settings ──
export const getStatus = () => request<SequencerStatus>(`${BASE}/status`)
export const getSettings = () => request<SequencerSettings>(`${BASE}/settings`)
export const putSettings = (s: SequencerSettings) =>
  request<SequencerSettings>(`${BASE}/settings`, { method: 'PUT', body: JSON.stringify(s) })

// ── Other plugins, for the target picker (REST only — no cross-plugin imports) ──
export interface ObjectMatch {
  name: string
  aliases: string[]
  ra: number
  dec: number
  type: string
  source: string
}

export interface Favorite {
  id: string
  name: string
  ra: number
  dec: number
  object_name: string
  object_type: string
}

export const searchObjects = (q: string) =>
  request<ObjectMatch[]>(`/plugins/object_resolver/search?q=${encodeURIComponent(q)}&limit=12`)

export const getFavorites = async (): Promise<Favorite[]> => {
  const s = await request<{ favorites: Favorite[] }>('/plugins/target/settings')
  return s.favorites ?? []
}
