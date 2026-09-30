export interface HistogramStats {
  histogram: number[]
  hist_min: number
  hist_max: number
  stretch_low: number
  stretch_high: number
}

/**
 * Boxed histogram with min/max axis labels and stretch black/white clip markers.
 *
 * `hist_min`/`hist_max` are expected to span the sensor's true full-scale ADU range
 * (not the sample's own min/max) so a spike hard against the right edge reliably means
 * real clipping — see astrolol.imaging.preview.fits_to_jpeg on the backend.
 */
export function HistogramOverlay({ stats }: { stats: HistogramStats }) {
  const { histogram, hist_min, hist_max, stretch_low, stretch_high } = stats
  const W = 170
  const H = 48
  const PAD = 12 // room for the min/max axis labels below the box
  const maxCount = Math.max(...histogram, 1)
  const range = hist_max - hist_min || 1
  const lowX = Math.max(0, Math.min(W, ((stretch_low - hist_min) / range) * W))
  const highX = Math.max(0, Math.min(W, ((stretch_high - hist_min) / range) * W))
  const bins = histogram.length

  return (
    <svg width={W} height={H + PAD} className="block">
      {histogram.map((count, i) => {
        const barH = (count / maxCount) * H
        const x = (i / bins) * W
        const bw = W / bins + 0.5
        return (
          <rect
            key={i}
            x={x} y={H - barH} width={bw} height={barH}
            fill="rgba(200,200,200,0.6)"
          />
        )
      })}
      {/* Stretch clip markers */}
      <line x1={lowX} y1={0} x2={lowX} y2={H} stroke="rgba(96,165,250,0.8)" strokeWidth={1} />
      <line x1={highX} y1={0} x2={highX} y2={H} stroke="rgba(251,191,36,0.8)" strokeWidth={1} />
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
  )
}
