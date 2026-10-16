import type { LogEntry } from '@/store'

/** Seconds a folded log stays open after the last new entry: warnings and errors get longer. */
export const PEEK_INFO_MS = 3000
export const PEEK_ALERT_MS = 8000

export const peekDuration = (level: string): number =>
  level === 'warning' || level === 'error' ? PEEK_ALERT_MS : PEEK_INFO_MS

/**
 * Entries to show, oldest first. The store keeps the newest first, so this reverses it: a panel
 * that follows its bottom then shows the latest lines.
 */
export function selectEntries(log: LogEntry[], filter?: string[], levels?: string[]): LogEntry[] {
  const out: LogEntry[] = []
  for (let i = log.length - 1; i >= 0; i--) {
    const e = log[i]
    if (filter && !filter.includes(e.component)) continue
    if (levels && !levels.includes(e.level)) continue
    out.push(e)
  }
  return out
}

/** The page a log belongs to, from the route: "/mount" -> "mount", "/imaging/cam1" -> "imaging". */
export const logPageKey = (pathname: string): string => pathname.split('/').filter(Boolean)[0] ?? 'home'
