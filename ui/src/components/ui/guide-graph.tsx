// Guide error over time: RA and Dec as two lines, with the RMS band. Shared by every guider.
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { fmtAgo, gridValues, type GuideSample } from '@/utils/guiding'

const GRAPH_H = 130
const MARGIN_L = 28 // left margin inside the SVG coordinate space for the y-axis labels
const X_AXIS_H = 14 // extra height below the graph for the x-axis tick labels

export function GuideGraph({
  points,
  range,
  rmsTotal,
  unit = '"',
}: {
  points: GuideSample[]
  range: number // full height of the graph, in `unit`
  rmsTotal?: number | null
  unit?: string
}) {
  const { t } = useTranslation()
  const wrapRef = useRef<HTMLDivElement>(null)
  const [W, setW] = useState(400)

  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const ro = new ResizeObserver((entries) => {
      const w = Math.round(entries[0].contentRect.width)
      if (w > 0) setW(w)
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  if (points.length === 0) {
    return (
      <div ref={wrapRef} className="flex items-center justify-center h-24 text-xs text-slate-600">
        {t('guideGraph.none')}
      </div>
    )
  }

  const halfRange = range / 2
  const dataW = W - MARGIN_L

  // value → SVG y (positive = up = smaller y)
  const toY = (v: number): number => GRAPH_H / 2 - (v / halfRange) * (GRAPH_H / 2)
  const n = points.length
  const toX = (i: number): number => MARGIN_L + (n <= 1 ? dataW / 2 : Math.round((i / (n - 1)) * dataW))
  const clampY = (y: number): number => Math.max(0, Math.min(GRAPH_H, y))

  const grid = gridValues(halfRange)
  const raPath = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${toX(i)},${clampY(toY(p.ra)).toFixed(1)}`).join(' ')
  const decPath = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${toX(i)},${clampY(toY(p.dec)).toFixed(1)}`).join(' ')

  // X-axis: 0 at the right ("now"), negative values going left. Keyed by index so the DOM
  // nodes are stable and only their content changes.
  const xTicks: Array<{ x: number; label: string }> = []
  if (n > 1) {
    const tLast = Date.parse(points[n - 1].ts)
    const numTicks = Math.min(5, n)
    for (let k = 0; k < numTicks; k++) {
      const idx = Math.round((k * (n - 1)) / (numTicks - 1))
      xTicks.push({ x: toX(idx), label: fmtAgo((tLast - Date.parse(points[idx].ts)) / 1000) })
    }
  }

  const rmsOn = rmsTotal != null && rmsTotal > 0
  const rmsY = rmsOn ? clampY(toY(rmsTotal)) : null
  const rmsYNeg = rmsOn ? clampY(toY(-rmsTotal)) : null

  return (
    <div ref={wrapRef} className="w-full">
      <svg width={W} height={GRAPH_H + X_AXIS_H} viewBox={`0 0 ${W} ${GRAPH_H + X_AXIS_H}`}>
        {grid.map((v) => {
          const isZero = Math.abs(v) < 0.001
          return (
            <line
              key={v}
              x1={MARGIN_L}
              y1={toY(v)}
              x2={W}
              y2={toY(v)}
              className={isZero ? 'stroke-slate-700' : 'stroke-slate-800'}
              strokeWidth={isZero ? 1 : 0.5}
              strokeDasharray={isZero ? '4 4' : undefined}
            />
          )
        })}
        {grid.filter((v) => Math.abs(v) > 0.001).map((v) => (
          <text key={v} x={MARGIN_L - 4} y={toY(v) + 3} fontSize="8" className="fill-slate-600" textAnchor="end">
            {v > 0 ? `+${v}` : `${v}`}
          </text>
        ))}

        {rmsY != null && rmsYNeg != null && (
          <>
            <line x1={MARGIN_L} y1={rmsY} x2={W} y2={rmsY} className="stroke-slate-400" strokeWidth={1} strokeDasharray="4 4" />
            <line x1={MARGIN_L} y1={rmsYNeg} x2={W} y2={rmsYNeg} className="stroke-slate-400" strokeWidth={1} strokeDasharray="4 4" />
            <text x={W - 2} y={rmsY - 3} fontSize="8" className="fill-slate-400" textAnchor="end">
              ±{rmsTotal!.toFixed(2)}{unit}
            </text>
          </>
        )}

        <path d={raPath} fill="none" className="stroke-series-1" strokeWidth={1.5} />
        <path d={decPath} fill="none" className="stroke-series-2" strokeWidth={1.5} />

        {xTicks.map(({ x, label }, idx) => (
          <text key={idx} x={x} y={GRAPH_H + 11} fontSize="8" className="fill-slate-600" textAnchor="middle">
            {label}
          </text>
        ))}

        <text x={MARGIN_L + 4} y={10} fontSize="9" className="fill-series-1">{t('guideGraph.ra')}</text>
        <text x={MARGIN_L + 22} y={10} fontSize="9" className="fill-series-2">{t('guideGraph.dec')}</text>
        {rmsY != null && <text x={MARGIN_L + 44} y={10} fontSize="9" className="fill-slate-400">{t('guideGraph.rms')}</text>}
      </svg>
    </div>
  )
}
