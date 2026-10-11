// Sign-in state. The backend decides whether credentials are needed at all
// (`enforced`); with the security plugin off, everyone is an admin and none of this shows.
import { create } from 'zustand'

export type AccessLevel = 'viewer' | 'operator' | 'admin'

export interface AuthStatus {
  enforced: boolean
  authenticated: boolean
  name: string | null
  level: AccessLevel | null
  kind: 'user' | 'guest' | 'token' | 'service' | null
  guest_allowed: boolean
  secure_transport: boolean
}

interface AuthState {
  status: AuthStatus | null
  /** A guest asked to sign in: show the form although they are already let in. */
  loginOpen: boolean
  refresh: () => Promise<void>
  login: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
  openLogin: (open: boolean) => void
}

async function fetchStatus(): Promise<AuthStatus | null> {
  try {
    const res = await fetch('/auth/status')
    return res.ok ? ((await res.json()) as AuthStatus) : null
  } catch {
    return null
  }
}

export const useAuth = create<AuthState>((set, get) => ({
  status: null,
  loginOpen: false,
  refresh: async () => {
    const status = await fetchStatus()
    // Backend unreachable: keep what we know; the app shows its own offline state.
    if (status) set({ status })
    else if (get().status === null) set({ status: { enforced: false, authenticated: true, name: null, level: 'admin', kind: null, guest_allowed: false, secure_transport: true } })
  },
  login: async (username, password) => {
    const res = await fetch('/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    })
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      throw new Error(body.detail ?? `HTTP ${res.status}`)
    }
    set({ loginOpen: false })
    await get().refresh()
  },
  logout: async () => {
    await fetch('/auth/logout', { method: 'POST' }).catch(() => {})
    set({ loginOpen: false })
    await get().refresh()
  },
  openLogin: (open) => set({ loginOpen: open }),
}))

export const canOperate = (s: AuthStatus | null) => s?.level === 'operator' || s?.level === 'admin'

/** True on a connection where a password would travel in clear (plain HTTP to a non-local host). */
export function isInsecureTransport(s: AuthStatus | null): boolean {
  if (!s || s.secure_transport) return false
  const h = window.location.hostname
  return !(h === 'localhost' || h === '127.0.0.1' || h === '::1' || h === '[::1]')
}
