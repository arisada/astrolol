// Plugin-local API client — keeps platesolve routes out of the core client.ts.
// Copy of the request helper is intentional (see plugin UI guidelines in CLAUDE.md).

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

// ── Types ──────────────────────────────────────────────────────────────────────

export interface PlatesolveSettings {
  astap_bin: string
  astap_db_path: string
  astap_search_radius: number
  astap_tolerance: number
  pixel_size_um: number | null
  exposure_duration: number
  binning: number
  after_solve: string   // 'nothing' | 'sync' | 'sync_slew'
}

export interface SolveRequest {
  fits_path: string
  ra_hint?: number | null
  dec_hint?: number | null
  radius?: number
  fov?: number | null
}

export interface SolveResult {
  ra: number
  dec: number
  rotation: number
  pixel_scale: number
  field_w: number
  field_h: number
  duration_ms: number
}

export interface DbStatus {
  installed: boolean
  db_path: string
}

export type SolveJobStatus = 'pending' | 'exposing' | 'solving' | 'completed' | 'failed' | 'cancelled'

export interface SolveJob {
  id: string
  status: SolveJobStatus
  request: SolveRequest
  result?: SolveResult | null
  error?: string | null
  created_at: string
  completed_at?: string | null
}

// Plugin state stored in Zustand pluginStates['platesolve']
export interface PlateSolvePluginState {
  jobs: Record<string, SolveJob>
}

export const DEFAULT_PLATESOLVE_STATE: PlateSolvePluginState = {
  jobs: {},
}

// ── API functions ───────────────────────────────────────────────────────────────

export const exposeAndSolve = (body: { device_id: string; duration: number; binning: number; gain?: number | null }) =>
  request<SolveJob>('/plugins/platesolve/expose_and_solve', { method: 'POST', body: JSON.stringify(body) })

export const solve = (req: SolveRequest) =>
  request<SolveJob>('/plugins/platesolve/solve', { method: 'POST', body: JSON.stringify(req) })

export const jobs = () => request<SolveJob[]>('/plugins/platesolve/jobs')

export const jobStatus = (jobId: string) => request<SolveJob>(`/plugins/platesolve/${jobId}/status`)

export const cancel = (jobId: string) =>
  request<void>(`/plugins/platesolve/${jobId}/cancel`, { method: 'DELETE' })

export const dbStatus = () => request<DbStatus>('/plugins/platesolve/db_status')

export const installDb = () =>
  request<{ status: string }>('/plugins/platesolve/install_db', { method: 'POST' })

export const getSettings = () => request<PlatesolveSettings>('/plugins/platesolve/settings')

export const putSettings = (body: PlatesolveSettings) =>
  request<PlatesolveSettings>('/plugins/platesolve/settings', { method: 'PUT', body: JSON.stringify(body) })
