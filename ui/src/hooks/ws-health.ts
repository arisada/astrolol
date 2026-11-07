// When to stop trusting the event socket. The server sends something at least every 10 s
// (events or a heartbeat), so silence means the connection is gone even if the browser still
// calls it open: a phone that slept, a switched wifi, a proxy that dropped it.

export const STALE_AFTER_MS = 30_000
// On coming back to the tab, much less silence is already suspicious.
export const STALE_ON_WAKE_MS = 12_000

const CONNECTING = 0
const OPEN = 1

export function isStale(lastMessageAt: number, now: number, limit = STALE_AFTER_MS): boolean {
  return now - lastMessageAt > limit
}

/**
 * The socket must be replaced when it is closed (or closing), or has been silent for too long.
 * One that is still connecting gets the same time to come up as an open one gets to speak.
 */
export function mustReconnect(readyState: number | undefined, lastMessageAt: number, now: number, limit = STALE_AFTER_MS): boolean {
  if (readyState === OPEN || readyState === CONNECTING) return isStale(lastMessageAt, now, limit)
  return true
}

export type ControlMessage = 'ws.heartbeat' | 'ws.resync'

export function controlMessage(type: string): ControlMessage | null {
  return type === 'ws.heartbeat' || type === 'ws.resync' ? type : null
}
