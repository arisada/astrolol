// Client-side mirror of the auto-stretch math in astrolol/imaging/preview.py, so the
// histogram can draw the transfer curve for the current slider values without a
// round trip. The server stays the source of truth for the rendered image.

export interface StretchParams {
  target_bg: number      // display brightness the sky background is lifted to (0–1)
  shadows_sigma: number  // black point, in noise σ relative to the background (≤ 0)
}

export const DEFAULT_STRETCH_PARAMS: StretchParams = { target_bg: 0.25, shadows_sigma: -2.8 }

/** Midtones transfer function: maps 0 → 0, m → 0.5, 1 → 1. */
export function mtf(m: number, x: number): number {
  if (x <= 0) return 0
  if (x >= 1) return 1
  return ((m - 1) * x) / ((2 * m - 1) * x - m)
}

export interface StretchStats {
  stretch_low: number
  stretch_high: number
  stretch_midtone?: number
  display_median?: number
  display_sigma?: number
}

/** Black point, white point (ADU) and midtones balance for *params* — or, without
 *  params (or without the display statistics needed), the ones the server used. */
export function computeStretch(
  stats: StretchStats, fullScale: number, params?: StretchParams,
): { low: number; high: number; m: number } {
  const median = stats.display_median
  const sigma = stats.display_sigma
  if (!params || median == null || sigma == null) {
    return { low: stats.stretch_low, high: stats.stretch_high, m: stats.stretch_midtone ?? 0.5 }
  }
  const high = fullScale
  if (sigma <= 0 || high <= 0) return { low: 0, high, m: 0.5 }
  const low = Math.min(Math.max(median + params.shadows_sigma * sigma, 0), high)
  const span = high - low
  if (span <= 0) return { low, high, m: 0.5 }
  const x0 = (median - low) / span
  if (x0 <= 0 || x0 >= params.target_bg) return { low, high, m: 0.5 }
  return { low, high, m: mtf(params.target_bg, x0) }
}
