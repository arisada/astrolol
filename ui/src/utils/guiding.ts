// Pure helpers behind the guide graph and the guide target.

export interface GuideSample {
  ra: number
  dec: number
  ts: string // ISO timestamp
}

/** Format an elapsed time as a negative label, e.g. "-1m30s", "-45s", "0". */
export function fmtAgo(secondsAgo: number): string {
  if (secondsAgo < 1) return '0'
  if (secondsAgo < 60) return `-${Math.round(secondsAgo)}s`
  const m = Math.floor(secondsAgo / 60)
  const s = Math.round(secondsAgo % 60)
  return s === 0 ? `-${m}m` : `-${m}m${s}s`
}

const GRID_STEPS = [0.1, 0.2, 0.25, 0.5, 1, 2, 4, 5, 8, 10, 20, 50]

/** Grid spacing for a display spanning ±halfRange: at most four lines each side of zero. */
export function gridStep(halfRange: number): number {
  return GRID_STEPS.find((s) => halfRange / s <= 4) ?? GRID_STEPS[GRID_STEPS.length - 1]
}

/** Grid values within ±halfRange, as multiples of the step: zero is always one. */
export function gridValues(halfRange: number): number[] {
  const step = gridStep(halfRange)
  const n = Math.floor(halfRange / step + 1e-9)
  const out: number[] = []
  for (let k = -n; k <= n; k++) out.push(Math.round(k * step * 1000) / 1000)
  return out
}

const RANGES = [0.5, 1, 2, 4, 6, 8, 12, 16, 24, 32, 64]

/** The smallest display span (full height, ± half each side) that holds every value. */
export function niceRange(values: number[]): number {
  const maxAbs = values.reduce((m, v) => Math.max(m, Math.abs(v)), 0)
  const needed = maxAbs * 2 * 1.15
  return RANGES.find((r) => r >= needed) ?? Math.ceil(needed)
}

export function rmsOf(points: GuideSample[]): { ra: number; dec: number; total: number } | null {
  if (points.length === 0) return null
  const ra = Math.sqrt(points.reduce((s, p) => s + p.ra * p.ra, 0) / points.length)
  const dec = Math.sqrt(points.reduce((s, p) => s + p.dec * p.dec, 0) / points.length)
  return { ra, dec, total: Math.hypot(ra, dec) }
}

/** A point's place on a target of the given radius, clamped to its edge so it never leaves. */
export function targetPosition(
  p: { ra: number; dec: number },
  halfRange: number,
  radius: number,
): { x: number; y: number; clamped: boolean } {
  let x = (p.ra / halfRange) * radius
  let y = (-p.dec / halfRange) * radius // North is up
  const r = Math.hypot(x, y)
  const clamped = r > radius
  if (clamped) {
    x = (x / r) * radius
    y = (y / r) * radius
  }
  return { x, y, clamped }
}
