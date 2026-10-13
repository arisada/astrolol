// The error pop-up remembers, per browser, the last error the user dismissed. The server replays
// its recent events on every page load; without this, a dismissed error would pop up again.

const KEY = 'astrolol.dismissedErrorAt'

/** Whether an error raised at `timestamp` is covered by the dismissal made at `dismissedAt`. */
export function isDismissed(timestamp: string, dismissedAt: string | null): boolean {
  if (!dismissedAt) return false
  const at = Date.parse(timestamp)
  const until = Date.parse(dismissedAt)
  if (Number.isNaN(at) || Number.isNaN(until)) return false
  return at <= until
}

/** The later of two dismissal times, so dismissing an older error never brings newer ones back. */
export function laterDismissal(a: string | null, b: string): string {
  return a && isDismissed(b, a) ? a : b
}

export function loadDismissedAt(): string | null {
  try { return localStorage.getItem(KEY) } catch { return null }
}

export function saveDismissedAt(timestamp: string): void {
  try { localStorage.setItem(KEY, timestamp) } catch { /* storage unavailable */ }
}
