// Target plugin — typed fetch helpers mirroring api.py routes.

export interface AltitudePoint {
  time: string  // UTC ISO string
  alt: number   // degrees above horizon
}

export interface TwilightTimes {
  astronomical_dusk: string | null
  nautical_dusk: string | null
  civil_dusk: string | null
  civil_dawn: string | null
  nautical_dawn: string | null
  astronomical_dawn: string | null
}

export interface EphemerisResult {
  rise: string | null
  transit: string | null
  set: string | null
  circumpolar: boolean
  never_rises: boolean
  peak_alt: number | null
  peak_time: string | null
  imaging_window_start: string | null
  imaging_window_end: string | null
  not_observable_at_night: boolean
  altitude_curve: AltitudePoint[]
  twilight: TwilightTimes
  moon_separation: number | null
  moon_illumination: number | null
  observer_location_missing: boolean
}

export interface FavoriteTarget {
  id: string
  name: string
  ra: number
  dec: number
  object_name: string
  object_type: string
  notes: string
  added_at: string
}

export interface TargetSettings {
  favorites: FavoriteTarget[]
  min_altitude_deg: number
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText)
    throw new Error(`${res.status} ${text}`)
  }
  return res.json() as Promise<T>
}

export const getSettings = () =>
  request<TargetSettings>('/plugins/target/settings')

export const putSettings = (s: TargetSettings) =>
  request<TargetSettings>('/plugins/target/settings', {
    method: 'PUT',
    body: JSON.stringify(s),
  })

export const getEphemeris = (ra: number, dec: number, date?: string) => {
  const params = new URLSearchParams({ ra: String(ra), dec: String(dec) })
  if (date) params.set('date', date)
  return request<EphemerisResult>(`/plugins/target/ephemeris?${params}`)
}

// Mount API calls (no plugin wrapper — calling core mount routes directly)
export const setMountTarget = (deviceId: string, ra: number, dec: number, name: string) =>
  request<void>(`/mount/${deviceId}/target`, {
    method: 'PUT',
    body: JSON.stringify({ ra, dec, name, source: 'target_plugin' }),
  })

export const slewMount = (deviceId: string) =>
  request<void>(`/mount/${deviceId}/slew`, { method: 'POST' })
