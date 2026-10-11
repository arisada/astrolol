export type Level = 'viewer' | 'operator' | 'admin'

export interface SecuritySettings {
  guest_enabled: boolean
  allowed_origins: string[]
}
export interface UserOut { name: string; level: Level; created: string }
export interface TokenOut {
  id: string
  name: string
  level: Level
  hint: string
  created: string
  expires: string | null
  last_used: string | null
}
export interface TokenCreated extends TokenOut { token: string }

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    const detail = body.detail
    throw new Error(typeof detail === 'string' ? detail : `${options?.method ?? 'GET'} ${path} failed: ${res.status}`)
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

const base = '/plugins/security'
export const getSettings = () => request<SecuritySettings>(`${base}/settings`)
export const putSettings = (s: SecuritySettings) =>
  request<SecuritySettings>(`${base}/settings`, { method: 'PUT', body: JSON.stringify(s) })

export const listUsers = () => request<UserOut[]>(`${base}/users`)
export const createUser = (name: string, password: string, level: Level) =>
  request<UserOut>(`${base}/users`, { method: 'POST', body: JSON.stringify({ name, password, level }) })
export const updateUser = (name: string, patch: { password?: string; level?: Level }) =>
  request<UserOut>(`${base}/users/${encodeURIComponent(name)}`, { method: 'PUT', body: JSON.stringify(patch) })
export const deleteUser = (name: string) =>
  request<void>(`${base}/users/${encodeURIComponent(name)}`, { method: 'DELETE' })
export const changeOwnPassword = (current_password: string, new_password: string) =>
  request<void>(`${base}/me/password`, { method: 'POST', body: JSON.stringify({ current_password, new_password }) })

export const listTokens = () => request<TokenOut[]>(`${base}/tokens`)
export const createToken = (name: string, level: Level, expires_in_days: number | null) =>
  request<TokenCreated>(`${base}/tokens`, { method: 'POST', body: JSON.stringify({ name, level, expires_in_days }) })
export const deleteToken = (id: string) => request<void>(`${base}/tokens/${id}`, { method: 'DELETE' })
