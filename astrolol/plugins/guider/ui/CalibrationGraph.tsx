// What the calibration measured: where the star was after every pulse, drawn as it sits on the
// sensor (pixels, y down). West and East share one colour, North and South the other; the way
// back is dashed. Hollow points were left out of the fit (the slack at a reversal).
import { useTranslation } from 'react-i18next'
import type { Calibration, CalibrationPhase } from './api'
import { phasePoints, traceBounds } from './calibration'

const SIZE = 320
const PAD = 14
const STYLE: Record<'west' | 'east' | 'north' | 'south', { line: string; fill: string; dash?: string }> = {
  west: { line: 'stroke-series-1', fill: 'fill-series-1' },
  east: { line: 'stroke-series-1', fill: 'fill-series-1', dash: '4 3' },
  north: { line: 'stroke-series-2', fill: 'fill-series-2' },
  south: { line: 'stroke-series-2', fill: 'fill-series-2', dash: '4 3' },
}
const SWEEPS = ['west', 'east', 'north', 'south'] as const

export function CalibrationGraph({ calibration }: { calibration: Calibration }) {
  const { t } = useTranslation('guider')
  const trace = calibration.trace
  if (trace.length === 0) return <p className="text-xs text-slate-500">{t('calibration.noTrace')}</p>

  const b = traceBounds(trace)
  const span = b.maxX - b.minX
  const k = (SIZE - 2 * PAD) / span
  const X = (x: number) => PAD + (x - b.minX) * k
  const Y = (y: number) => PAD + (y - b.minY) * k
  const label: Record<CalibrationPhase, string> = {
    drift: t('calibration.phase_drift'),
    probe: t('calibration.phase_probe'),
    west: t('calibration.phase_west'),
    east: t('calibration.phase_east'),
    north: t('calibration.phase_north'),
    south: t('calibration.phase_south'),
  }
  const start = phasePoints(trace, 'west')[0] ?? trace[0]
  // The fitted axes, drawn from the start for the span of one sweep step's worth of pulses.
  const reach = (span / 3) / Math.max(calibration.ra_x ** 2 + calibration.ra_y ** 2, 1e-12) ** 0.5
  const axis = (vx: number, vy: number) => ({ x: X(start.x + vx * reach), y: Y(start.y + vy * reach) })
  const ra = axis(calibration.ra_x, calibration.ra_y)
  const dec = axis(calibration.dec_x, calibration.dec_y)
  const scaleBar = niceBar(span / 4)

  return (
    <div className="flex flex-col gap-2">
      <svg viewBox={`0 0 ${SIZE} ${SIZE}`} className="w-full max-w-[360px] aspect-square rounded border border-surface-border bg-surface" role="img" aria-label={t('calibration.graph')}>
        <defs>
          <marker id="cal-arrow" viewBox="0 0 6 6" refX="5" refY="3" markerWidth="5" markerHeight="5" orient="auto">
            <path d="M0,0 L6,3 L0,6 z" className="fill-slate-400" />
          </marker>
        </defs>

        {/* drift and probe: context, small and grey */}
        {trace.filter((p) => p.phase === 'drift' || p.phase === 'probe').map((p, i) => (
          <circle key={`ctx-${i}`} cx={X(p.x)} cy={Y(p.y)} r={1.6} className="fill-slate-600" />
        ))}

        {SWEEPS.map((phase) => {
          const pts = phasePoints(trace, phase)
          if (pts.length === 0) return null
          const st = STYLE[phase]
          return (
            <g key={phase}>
              <polyline points={pts.map((p) => `${X(p.x)},${Y(p.y)}`).join(' ')} fill="none" className={st.line} strokeWidth={1.3} strokeDasharray={st.dash} opacity={0.8} />
              {pts.map((p) => (p.used
                ? <circle key={p.step} cx={X(p.x)} cy={Y(p.y)} r={2.6} className={st.fill} />
                : <circle key={p.step} cx={X(p.x)} cy={Y(p.y)} r={3} fill="none" className={st.line} strokeWidth={1.2} />
              ))}
            </g>
          )
        })}

        {/* the fitted axes */}
        <line x1={X(start.x)} y1={Y(start.y)} x2={ra.x} y2={ra.y} className="stroke-slate-400" strokeWidth={1} markerEnd="url(#cal-arrow)" />
        <line x1={X(start.x)} y1={Y(start.y)} x2={dec.x} y2={dec.y} className="stroke-slate-400" strokeWidth={1} markerEnd="url(#cal-arrow)" />
        <text x={ra.x + 3} y={ra.y - 3} fontSize="9" className="fill-slate-400">{t('calibration.axisRa')}</text>
        <text x={dec.x + 3} y={dec.y - 3} fontSize="9" className="fill-slate-400">{t('calibration.axisDec')}</text>
        <circle cx={X(start.x)} cy={Y(start.y)} r={5} fill="none" className="stroke-slate-200" strokeWidth={1} />

        {/* scale */}
        <line x1={PAD} y1={SIZE - 8} x2={PAD + scaleBar * k} y2={SIZE - 8} className="stroke-slate-500" strokeWidth={1.5} />
        <text x={PAD + scaleBar * k + 4} y={SIZE - 5} fontSize="9" className="fill-slate-500">{scaleBar} px</text>
      </svg>

      <ul className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-slate-500">
        {SWEEPS.map((phase) => (
          <li key={phase} className="flex items-center gap-1.5">
            <svg width="22" height="8"><line x1="1" y1="4" x2="21" y2="4" className={STYLE[phase].line} strokeWidth="1.5" strokeDasharray={STYLE[phase].dash} /></svg>
            {label[phase]}
          </li>
        ))}
        <li className="flex items-center gap-1.5">
          <svg width="10" height="10"><circle cx="5" cy="5" r="3.5" fill="none" className="stroke-slate-400" strokeWidth="1.2" /></svg>
          {t('calibration.leftOut')}
        </li>
      </ul>
    </div>
  )
}

/** A round number of pixels for the scale bar: 1, 2, 5, 10, 20, 50 … */
function niceBar(target: number): number {
  if (!(target > 0)) return 1
  const pow = 10 ** Math.floor(Math.log10(target))
  const m = target / pow
  return (m >= 5 ? 5 : m >= 2 ? 2 : 1) * pow
}
