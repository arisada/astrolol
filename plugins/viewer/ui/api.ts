// Viewer plugin — fetch helpers mirroring plugins/viewer/api.py.
// REST-only response shapes are defined locally here (not in ui/src/api/types.ts) since
// nothing here flows through the WebSocket/store — only the ViewerXxxEvent types do.

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

export interface ViewerSettings {
  library_dir: string
}

export interface ImageRecord {
  id: string
  path: string
  size_bytes: number
  mtime: number
  captured_at: string
  captured_at_estimated: boolean
  frame_type: string
  object_name: string
  exposure_s: number | null
  gain: number | null
  binning: number | null
  filter_name: string
  camera_name: string
  telescope_name: string
  ra_deg: number | null
  dec_deg: number | null
  coord_source: 'wcs' | 'header_icrs' | 'header_jnow' | null
  ccd_temp: number | null
  width: number | null
  height: number | null
  night: string
  bg_median: number | null
  star_count: number | null
  hfr: number | null
  indexed_at: string
}

export interface ImageListResponse {
  items: ImageRecord[]
  total: number
  next_cursor: string | null
}

export interface GroupSummary {
  frame_type: string
  object_name: string
  filter_name: string
  camera_name: string
  exposure_s: number | null
  binning: number | null
  gain: number | null
  night: string
  count: number
  total_exposure_s: number
  first_captured_at: string
  last_captured_at: string
  representative_id: string
  ra_deg: number | null
  dec_deg: number | null
  sky_cell_ra: number | null
  sky_cell_dec: number | null
}

export interface GroupListResponse {
  items: GroupSummary[]
  total: number
}

export interface Facets {
  objects: string[]
  frame_types: string[]
  filters: string[]
  cameras: string[]
}

export interface RollupRow {
  object_name: string
  frame_count: number
  total_exposure_s: number
  nights: number
  first_captured_at: string
  last_captured_at: string
}

export interface LibraryStatus {
  library_dir: string
  total_bytes: number
  free_bytes: number
  image_count: number
  rescanning: boolean
  rejected_count: number
  rejected_bytes: number
}

export interface RejectedItem {
  relative_path: string
  size_bytes: number
  mtime: number
}

export interface ImageStats {
  histogram: number[]
  hist_min: number
  hist_max: number
  stretch_low: number
  stretch_high: number
  mean: number
  median: number
}

export interface ImageFilterParams {
  frame_type?: string[]
  object_name?: string
  filter_name?: string
  camera_name?: string
  exposure_s?: number
  binning?: number
  gain?: number
  night?: string
  sky_cell_ra?: number
  sky_cell_dec?: number
  date_from?: string
  date_to?: string
  search?: string
  star_count_min?: number
  star_count_max?: number
  hfr_min?: number
  hfr_max?: number
  ra_deg?: number
  dec_deg?: number
  radius_deg?: number
  before_captured_at?: string
  before_id?: string
  ascending?: boolean
  limit?: number
}

export interface GroupFilterParams {
  frame_type?: string[]
  object_name?: string
  filter_name?: string
  camera_name?: string
  date_from?: string
  date_to?: string
  search?: string
  page?: number
  page_size?: number
}

function toQuery(params: Record<string, unknown>): string {
  const usp = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    if (Array.isArray(value)) {
      value.forEach((v) => usp.append(key, String(v)))
    } else {
      usp.append(key, String(value))
    }
  }
  const s = usp.toString()
  return s ? `?${s}` : ''
}

export const getSettings = () => request<ViewerSettings>('/plugins/viewer/settings')
export const putSettings = (s: ViewerSettings) =>
  request<ViewerSettings>('/plugins/viewer/settings', { method: 'PUT', body: JSON.stringify(s) })

export const getStatus = () => request<LibraryStatus>('/plugins/viewer/status')

export const startRescan = () => request<{ status: string; library_dir: string }>('/plugins/viewer/rescan', { method: 'POST' })
export const cancelRescan = () => request<void>('/plugins/viewer/rescan', { method: 'DELETE' })

export const getFacets = () => request<Facets>('/plugins/viewer/facets')
export const getRollup = () => request<RollupRow[]>('/plugins/viewer/rollup')

export const listGroups = (params: GroupFilterParams) =>
  request<GroupListResponse>(`/plugins/viewer/groups${toQuery(params as Record<string, unknown>)}`)

export const listImages = (params: ImageFilterParams) =>
  request<ImageListResponse>(`/plugins/viewer/images${toQuery(params as Record<string, unknown>)}`)

export const getImage = (id: string) => request<ImageRecord>(`/plugins/viewer/images/${id}`)

export const getStats = (id: string) => request<ImageStats>(`/plugins/viewer/images/${id}/stats`)

export const thumbnailUrl = (id: string) => `/plugins/viewer/images/${id}/thumbnail`

export const previewUrl = (id: string, opts: { mode?: 'auto' | 'linear'; black_pct?: number; white_pct?: number; quality?: number }) =>
  `/plugins/viewer/images/${id}/preview.jpg${toQuery(opts as Record<string, unknown>)}`

export const fitsDownloadUrl = (id: string) => `/plugins/viewer/images/${id}/fits`

export const rejectImage = (id: string) => request<void>(`/plugins/viewer/images/${id}/reject`, { method: 'POST' })

export const listRejected = () => request<RejectedItem[]>('/plugins/viewer/rejected')
export const unrejectImage = (relativePath: string) =>
  request<void>('/plugins/viewer/rejected/unreject', { method: 'POST', body: JSON.stringify({ relative_path: relativePath }) })
export const emptyRejected = () => request<void>('/plugins/viewer/rejected/empty', { method: 'POST' })
