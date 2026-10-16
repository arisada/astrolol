import { useTranslation } from 'react-i18next'
import type { CurveFit, FitAlgo, FocusDataPoint, FocusMetric } from '@/api/types'

// ── U-curve SVG chart ─────────────────────────────────────────────────────────

export function UCurveChart({
  dataPoints,
  curveFit,
  optimal,
  fitAlgo,
  metric,
}: {
  dataPoints: FocusDataPoint[]
  curveFit: CurveFit | null
  optimal: number | null
  fitAlgo: FitAlgo
  metric: FocusMetric
}) {
  const { t } = useTranslation('autofocus')
  const W = 260, H = 150
  const pad = { t: 8, r: 10, b: 24, l: 34 }
  const cw = W - pad.l - pad.r
  const ch = H - pad.t - pad.b

  if (dataPoints.length === 0) {
    return (
      <div className="flex items-center justify-center h-[150px] text-xs text-slate-600">
        {t('noData')}
      </div>
    )
  }

  const positions = dataPoints.map((d) => d.position)
  const fwhms = dataPoints.filter((d) => d.fwhm > 0).map((d) => d.fwhm)
  if (fwhms.length === 0) return null

  const minX = Math.min(...positions)
  const maxX = Math.max(...positions)
  const maxY = Math.max(...fwhms) * 1.2
  const rangeX = maxX - minX || 1

  const toX = (pos: number) => pad.l + ((pos - minX) / rangeX) * cw
  const toY = (fwhm: number) => pad.t + (1 - fwhm / maxY) * ch

  // Fitted curve — sampled at 80 points across the range
  let curvePath = ''
  if (curveFit) {
    const { a, b, c } = curveFit
    const pts = Array.from({ length: 80 }, (_, i) => {
      const x = minX + (i / 79) * rangeX
      const y = fitAlgo === 'hyperbola'
        ? Math.sqrt(Math.max(0, a * x * x + b * x + c))
        : a * x * x + b * x + c
      if (y < 0 || y > maxY * 1.1) return null
      return `${toX(x).toFixed(1)},${toY(y).toFixed(1)}`
    }).filter(Boolean)
    if (pts.length >= 2) curvePath = `M ${pts.join(' L ')}`
  }

  const showOptimal =
    optimal !== null && optimal >= minX - rangeX * 0.05 && optimal <= maxX + rangeX * 0.05

  const yLabels = [maxY, maxY / 2, 0]

  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} className="block">
      <rect x={pad.l} y={pad.t} width={cw} height={ch} className="fill-surface stroke-slate-800" strokeWidth={0.5} />

      {yLabels.map((fwhm, i) => (
        <g key={i}>
          <line x1={pad.l} y1={toY(fwhm)} x2={pad.l + cw} y2={toY(fwhm)} className="stroke-slate-800" strokeWidth={0.5} />
          <text x={pad.l - 3} y={toY(fwhm) + 3} textAnchor="end" className="fill-slate-600" fontSize={7}>
            {fwhm === 0 ? '0' : fwhm.toFixed(1)}
          </text>
        </g>
      ))}

      <text x={7} y={pad.t + ch / 2} textAnchor="middle" className="fill-slate-600" fontSize={7}
        transform={`rotate(-90 7 ${pad.t + ch / 2})`}>{metric === 'hfd' ? t('hfdAxis') : t('fwhmAxis')}</text>

      {Array.from({ length: Math.min(5, positions.length) }, (_, i) => {
        const pos = rangeX === 0
          ? minX
          : Math.round(minX + (i / (Math.min(5, positions.length) - 1 || 1)) * rangeX)
        return (
          <g key={i}>
            <line x1={toX(pos)} y1={pad.t + ch} x2={toX(pos)} y2={pad.t + ch + 3} className="stroke-slate-700" strokeWidth={0.5} />
            <text x={toX(pos)} y={H - 4} textAnchor="middle" className="fill-slate-600" fontSize={6.5}>{pos}</text>
          </g>
        )
      })}

      {curvePath && (
        <path d={curvePath} className="stroke-series-2" fill="none" strokeWidth={1.5} strokeLinejoin="round" />
      )}

      {showOptimal && (
        <line x1={toX(optimal!)} y1={pad.t} x2={toX(optimal!)} y2={pad.t + ch}
          className="stroke-green-400" strokeWidth={1} strokeDasharray="3,2" />
      )}

      {dataPoints.filter((dp) => dp.fwhm > 0).map((dp, i) => (
        <circle key={i} cx={toX(dp.position)} cy={toY(dp.fwhm)}
          r={3} className="fill-series-1 stroke-sky-700" strokeWidth={0.5} />
      ))}
    </svg>
  )
}
