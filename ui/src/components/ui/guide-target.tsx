// Where the guide star has been lately, as dots around the aim point: RA across, Dec up.
// A tight cluster on the centre is good guiding; a drifting or elongated cloud shows which
// axis is struggling.
import { useTranslation } from 'react-i18next'
import { gridValues, targetPosition, type GuideSample } from '@/utils/guiding'

const SIZE = 200
const C = SIZE / 2
const RADIUS = 86 // leaves room for the axis labels

export function GuideTarget({
  points,
  range,
  rmsTotal,
  unit = '"',
  recent = 60,
}: {
  points: GuideSample[]
  range: number // full width of the target, in `unit`
  rmsTotal?: number | null
  unit?: string
  recent?: number // how many of the latest points to show
}) {
  const { t } = useTranslation()
  const half = range / 2
  const shown = points.slice(-recent)
  const last = shown[shown.length - 1]
  const rings = gridValues(half).filter((v) => v > 0.001)
  const rmsRadius = rmsTotal != null && rmsTotal > 0 ? Math.min(RADIUS, (rmsTotal / half) * RADIUS) : null

  return (
    <svg viewBox={`0 0 ${SIZE} ${SIZE}`} className="w-full max-w-[260px] aspect-square" role="img" aria-label={t('guideTarget.label')}>
      <g transform={`translate(${C} ${C})`}>
        {rings.map((v) => (
          <g key={v}>
            <circle r={(v / half) * RADIUS} fill="none" className="stroke-slate-800" strokeWidth={0.7} />
            <text x={(v / half) * RADIUS + 2} y={-2} fontSize="7" className="fill-slate-500">{v}{unit}</text>
          </g>
        ))}
        <circle r={RADIUS} fill="none" className="stroke-slate-700" strokeWidth={1} />
        <line x1={-RADIUS} x2={RADIUS} y1={0} y2={0} className="stroke-slate-700" strokeWidth={0.7} />
        <line y1={-RADIUS} y2={RADIUS} x1={0} x2={0} className="stroke-slate-700" strokeWidth={0.7} />
        {rmsRadius != null && (
          <circle r={rmsRadius} fill="none" className="stroke-slate-400" strokeWidth={1} strokeDasharray="4 3" />
        )}

        {shown.map((p, i) => {
          const pos = targetPosition(p, half, RADIUS)
          if (p === last) return null
          // Older dots fade, so the cloud shows direction as well as spread.
          return (
            <circle
              key={`${p.ts}-${i}`}
              cx={pos.x}
              cy={pos.y}
              r={pos.clamped ? 1.4 : 2}
              className="fill-series-1"
              opacity={0.2 + (0.6 * (i + 1)) / shown.length}
            />
          )
        })}
        {last && (() => {
          const pos = targetPosition(last, half, RADIUS)
          return <circle cx={pos.x} cy={pos.y} r={3.5} className="fill-series-2 stroke-slate-100" strokeWidth={1} />
        })()}

        <text x={RADIUS - 2} y={10} fontSize="8" textAnchor="end" className="fill-slate-500">{t('guideTarget.ra')}</text>
        <text x={4} y={-RADIUS + 8} fontSize="8" className="fill-slate-500">{t('guideTarget.dec')}</text>
      </g>
    </svg>
  )
}
