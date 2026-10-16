import type { TFunction } from 'i18next'

/** Hour angle as "+1h 05m" / "−12m" (negative = east of the meridian). */
export function fmtHA(ha: number | null | undefined): string {
  if (ha == null) return '—'
  const sign = ha >= 0 ? '+' : '−'
  const abs = Math.abs(ha)
  const h = Math.floor(abs)
  const m = Math.floor((abs - h) * 60)
  if (h === 0) return `${sign}${m}m`
  return `${sign}${h}h ${String(m).padStart(2, '0')}m`
}

/** "1h 05m to meridian" / "12m past meridian" (uses the `mount` catalogue). */
export function fmtMeridianDistance(ha: number, t: TFunction): string {
  const abs = Math.abs(ha)
  const h = Math.floor(abs)
  const m = Math.floor((abs - h) * 60)
  const parts = h > 0 ? `${h}h ${m}m` : `${m}m`
  return t(ha < 0 ? 'meridianDistance.before' : 'meridianDistance.after', { time: parts })
}
