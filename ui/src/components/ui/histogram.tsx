import { computeStretch, mtf, type StretchParams, type StretchStats } from '@/utils/stretch'

export interface HistogramChannel extends StretchStats {
  name: 'R' | 'G' | 'B'
  histogram: number[]
  median: number
}

export interface HistogramStats extends StretchStats {
  histogram: number[]
  hist_min: number
  hist_max: number
  median?: number
  noise_sigma?: number
  saturated_pct?: number | null
  channels?: HistogramChannel[] | null
}

// Above this share of saturated pixels the readout turns amber.
const SATURATION_WARN_PCT = 0.1

const CHANNEL_RGB: Record<HistogramChannel['name'], string> = {
  R: '248,113,113',
  G: '74,222,128',
  B: '96,165,250',
}

/**
 * Boxed histogram with min/max axis labels, the stretch transfer curve and a
 * background / noise / saturation readout.
 *
 * `hist_min`/`hist_max` are expected to span the sensor's true full-scale ADU range
 * (not the sample's own min/max) so a spike hard against the right edge reliably means
 * real clipping — see astrolol.imaging.preview on the backend. Counts are drawn on a
 * log scale: on a linear one the background peak flattens everything else, hiding the
 * star/highlight tail that exposure decisions depend on.
 *
 * `params` redraws the curve for the given stretch settings (pass the values the
 * displayed image was rendered with); `linear` draws the identity ramp instead.
 * For a colour frame rendered in colour (`color`), each channel gets its own
 * histogram and curve — or one shared curve when `linked`.
 */
export function HistogramOverlay({
  stats, params, linear = false, color = false, linked = false,
}: {
  stats: HistogramStats
  params?: StretchParams
  linear?: boolean
  color?: boolean
  linked?: boolean
}) {
  const { hist_min, hist_max } = stats
  const W = 170
  const H = 48
  const PAD = 12 // room for the min/max axis labels below the box
  const range = hist_max - hist_min || 1
  const toX = (adu: number) => Math.max(0, Math.min(W, ((adu - hist_min) / range) * W))

  const channels = color && stats.channels?.length ? stats.channels : null
  const series = channels
    ? channels.map((ch) => ({
        histogram: ch.histogram,
        rgb: CHANNEL_RGB[ch.name],
        stretch: computeStretch(linked ? stats : ch, hist_max, params),
      }))
    : [{ histogram: stats.histogram, rgb: '200,200,200', stretch: computeStretch(stats, hist_max, params) }]
  // One shared count scale so channel heights stay comparable.
  const logMax = Math.log1p(Math.max(...series.flatMap((s) => s.histogram), 1))

  const curvePoints = ({ low, high, m }: { low: number; high: number; m: number }) => {
    const span = high - low
    const pts: string[] = []
    for (let px = 0; px <= W; px += 2) {
      const adu = hist_min + (px / W) * range
      const y = linear
        ? (adu - hist_min) / range
        : span > 0 ? mtf(m, Math.min(1, Math.max(0, (adu - low) / span))) : 0
      pts.push(`${px},${(H - y * H).toFixed(1)}`)
    }
    return pts.join(' ')
  }
  // Colour curves only differ when unlinked (and never in linear mode).
  const curves = channels && !linked && !linear
    ? series.map((s) => ({ points: curvePoints(s.stretch), stroke: `rgba(${s.rgb},0.9)`, low: s.stretch.low }))
    : [{ points: curvePoints(series[0].stretch), stroke: 'rgba(251,191,36,0.85)', low: series[0].stretch.low }]

  const sat = stats.saturated_pct
  return (
    <div className="flex flex-col gap-0.5">
      <svg width={W} height={H + PAD} className="block">
        {series.map((s, si) => {
          const bins = s.histogram.length
          return s.histogram.map((count, i) => {
            const barH = (Math.log1p(count) / logMax) * H
            return (
              <rect
                key={`${si}-${i}`}
                x={(i / bins) * W} y={H - barH} width={W / bins + 0.5} height={barH}
                fill={`rgba(${s.rgb},${channels ? 0.4 : 0.6})`}
              />
            )
          })
        })}
        {/* Transfer curve(s): input ADU (x) → display brightness (y). */}
        {curves.map((c, i) => (
          <polyline key={i} points={c.points} fill="none" stroke={c.stroke} strokeWidth={1} />
        ))}
        {/* Black point(s) */}
        {!linear && curves.map((c, i) => (
          <line
            key={`bp-${i}`} x1={toX(c.low)} y1={0} x2={toX(c.low)} y2={H}
            stroke={curves.length > 1 ? c.stroke : 'rgba(96,165,250,0.8)'} strokeWidth={1}
          />
        ))}
        {/* Box so the frame's ADU range (full sensor scale, not this shot's own min/max)
            reads clearly — a spike hard against the right edge means real clipping. */}
        <rect x={0.5} y={0.5} width={W - 1} height={H - 1} fill="none" stroke="rgba(148,163,184,0.5)" strokeWidth={1} />
        <text x={0} y={H + PAD - 1} fontSize={9} fill="rgba(148,163,184,0.9)" textAnchor="start">
          {Math.round(hist_min)}
        </text>
        <text x={W} y={H + PAD - 1} fontSize={9} fill="rgba(148,163,184,0.9)" textAnchor="end">
          {Math.round(hist_max)}
        </text>
      </svg>
      {stats.median != null && (
        <div className="flex justify-between text-[9px] font-mono text-slate-400 px-0.5">
          {stats.channels?.length ? (
            <span title="Sky background per channel (median, ADU)">
              Bg {stats.channels.map((ch) => Math.round(ch.median)).join('/')}
            </span>
          ) : (
            <span title="Sky background (median, ADU)">Bg {Math.round(stats.median)}</span>
          )}
          {stats.noise_sigma != null && (
            <span title="Background noise (σ, ADU)">σ {stats.noise_sigma.toFixed(1)}</span>
          )}
          {sat != null && (
            <span
              title="Pixels at full scale"
              className={sat > SATURATION_WARN_PCT ? 'text-amber-300' : undefined}
            >
              Sat {sat < 0.01 && sat > 0 ? '<0.01' : sat.toFixed(2)}%
            </span>
          )}
        </div>
      )}
    </div>
  )
}
