export interface AxisDiagnostics {
  cpr: number
  high_speed_ratio: number
  position_counts: number
  position_degrees: number
  step_period: number
  status: Record<string, boolean>
  extended_status: string
  reversed: boolean
}

export interface MountDiagnostics {
  device_id: string
  port: string | null
  baudrate: number | null
  board_version: string | null
  timer_freq: number | null
  tracking: boolean
  tracking_mode: string | null
  nudging: string[]
  location: [number, number, number] | null
  parked: boolean
  park_counts: [number, number] | null
  sync_offset: { ra_axis_h: number; dec_axis_deg: number } | null
  axes: Record<string, AxisDiagnostics>
  error: string | null
}

export interface EqmodSettings {
  led_brightness: number
}

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

export const getDiagnostics = () => request<MountDiagnostics[]>('/plugins/eqmod/diagnostics')
export const getSettings = () => request<EqmodSettings>('/plugins/eqmod/settings')
export const putSettings = (s: EqmodSettings) =>
  request<EqmodSettings>('/plugins/eqmod/settings', { method: 'PUT', body: JSON.stringify(s) })
