import { useTranslation } from 'react-i18next'
import type { ReticleState } from '@/api/types'

// Clock-position mapping: angle_deg=0 is straight up (the reticle's 0deg/12-o'clock
// mark). angle_deg is Hour Angle-based (SPEC.md section 2) and HA increases as a
// circumpolar star moves west over time -- which, looking north at the
// northern-hemisphere sky (the view this reticle models), is COUNTER-clockwise: the
// classic "star trails circle Polaris counter-clockwise" fact. Found by comparing
// against a real polar-scope app (PolarisView) at a known site/time: this code
// originally mapped increasing angle_deg to clockwise rotation, placing the dot at the
// mirror-image clock position (e.g. 6:50 shown where 5:10 was correct).
function clockToXY(angleDeg: number, radius: number, cx: number, cy: number) {
  const theta = (angleDeg * Math.PI) / 180
  return { x: cx - radius * Math.sin(theta), y: cy - radius * Math.cos(theta) }
}

export function ReticleDial({ state }: { state: ReticleState | null }) {
  const { t } = useTranslation('polar_align')
  const SIZE = 220
  const C = SIZE / 2
  const R = 86 // the engraved circle Polaris's dot should sit on

  const dot = state ? clockToXY(state.angle_deg, R, C, C) : null

  return (
    <div className="flex flex-col items-center gap-2">
      <svg viewBox={`0 0 ${SIZE} ${SIZE}`} width={SIZE} height={SIZE} className="block">
        {/* Bezel */}
        <circle cx={C} cy={C} r={C - 2} className="fill-surface stroke-slate-800" strokeWidth={1} />
        {/* Engraved circle Polaris should trace */}
        <circle cx={C} cy={C} r={R} fill="none" className="stroke-slate-700" strokeWidth={1} strokeDasharray="2,3" />
        {/* Clock ticks every 30deg, larger every 90deg */}
        {Array.from({ length: 12 }, (_, i) => {
          const deg = i * 30
          const major = deg % 90 === 0
          const inner = clockToXY(deg, R - (major ? 10 : 6), C, C)
          const outer = clockToXY(deg, R + (major ? 4 : 2), C, C)
          return (
            <line key={i} x1={inner.x} y1={inner.y} x2={outer.x} y2={outer.y}
              className={major ? 'stroke-slate-600' : 'stroke-slate-700'} strokeWidth={major ? 1.2 : 0.8} />
          )
        })}
        {/* True pole: dead centre */}
        <line x1={C - 5} y1={C} x2={C + 5} y2={C} className="stroke-slate-500" strokeWidth={0.8} />
        <line x1={C} y1={C - 5} x2={C} y2={C + 5} className="stroke-slate-500" strokeWidth={0.8} />

        {dot && (
          <circle cx={dot.x} cy={dot.y} r={5} className="fill-amber-400 stroke-surface" strokeWidth={1.5} />
        )}
      </svg>

      {state ? (
        <div className="text-center text-xs text-slate-400 space-y-0.5">
          <div>
            {t('reticle.angle')} <span className="text-slate-200 font-mono">{state.angle_deg.toFixed(1)}&deg;</span>
          </div>
        </div>
      ) : (
        <p className="text-xs text-slate-600">{t('reticle.none')}</p>
      )}
    </div>
  )
}
