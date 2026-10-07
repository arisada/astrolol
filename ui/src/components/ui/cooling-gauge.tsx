import { useId } from 'react'
import { niceTicks } from '@/utils/sky'

// Camera cooling: the outer half circle is the sensor temperature on a graduated scale with a tick
// at the set point; the inner half circle is the cooler power, shifting from the accent colour to
// amber and red as it nears its maximum. Scales to its parent via className.

const CX = 70
const CY = 64
const pt = (r: number, t: number): [number, number] => [CX - r * Math.cos(Math.PI * t), CY - r * Math.sin(Math.PI * t)]
const arc = (r: number, a: number, b: number) => {
  const [x1, y1] = pt(r, a)
  const [x2, y2] = pt(r, b)
  return `M${x1.toFixed(1)} ${y1.toFixed(1)}A${r} ${r} 0 0 1 ${x2.toFixed(1)} ${y2.toFixed(1)}`
}

export function CoolingGauge({ temperature, setPoint, power, min = -30, max = 20, label, className = 'w-full' }: {
  /** Sensor temperature, °C. */
  temperature: number
  /** Target temperature, °C. */
  setPoint?: number | null
  /** Cooler power, percent (0–100). */
  power?: number | null
  min?: number
  max?: number
  label: string
  className?: string
}) {
  const gid = useId()
  const frac = (v: number) => Math.min(1, Math.max(0, (v - min) / (max - min)))
  const fmt = (v: number, d = 0) => v.toFixed(d).replace('-', '−')
  const ticks = niceTicks(min, max, 5).major
  const p = power == null ? null : Math.min(1, Math.max(0, power / 100))

  return (
    <svg viewBox="0 0 140 84" className={className} role="img" aria-label={label}>
      <defs>
        <linearGradient id={gid} gradientUnits="userSpaceOnUse" x1={CX - 40} x2={CX + 40} y1={0} y2={0}>
          <stop offset="0" className="[stop-color:rgb(var(--c-accent))]" />
          <stop offset="0.55" className="[stop-color:rgb(var(--c-accent))]" />
          <stop offset="0.85" className="[stop-color:rgb(var(--c-status-busy))]" />
          <stop offset="1" className="[stop-color:rgb(var(--c-status-error))]" />
        </linearGradient>
      </defs>
      {ticks.map((v) => {
        const [x1, y1] = pt(46, frac(v))
        const [x2, y2] = pt(50, frac(v))
        const [lx, ly] = pt(58, frac(v))
        return (
          <g key={v}>
            <path d={`M${x1.toFixed(1)} ${y1.toFixed(1)}L${x2.toFixed(1)} ${y2.toFixed(1)}`} className="stroke-slate-500" strokeWidth={1} vectorEffect="non-scaling-stroke" />
            <text x={lx} y={ly + 2} textAnchor="middle" className="fill-slate-500 font-mono" fontSize={6.5}>{fmt(v)}</text>
          </g>
        )
      })}
      <path d={arc(48, 0, 1)} className="fill-none stroke-surface-border" strokeWidth={5} />
      <path d={arc(48, 0, frac(temperature))} className="fill-none stroke-accent" strokeWidth={5} />
      {setPoint != null && (() => {
        const [x1, y1] = pt(42, frac(setPoint))
        const [x2, y2] = pt(54, frac(setPoint))
        return <path d={`M${x1.toFixed(1)} ${y1.toFixed(1)}L${x2.toFixed(1)} ${y2.toFixed(1)}`} className="stroke-slate-100" strokeWidth={2} vectorEffect="non-scaling-stroke" />
      })()}
      {p != null && (
        <>
          <path d={arc(40, 0, 1)} className="fill-none stroke-surface-border" strokeWidth={4} />
          <path d={arc(40, 0, p)} fill="none" stroke={`url(#${gid})`} strokeWidth={4} />
        </>
      )}
      <text x={CX} y={CY - 12} textAnchor="middle" className="fill-slate-100 font-mono" fontSize={11}>{`${fmt(temperature, 1)} °C`}</text>
      <text x={CX} y={CY + 9} textAnchor="middle" className="fill-slate-500 font-mono" fontSize={6.5}>
        {[setPoint != null ? `set ${fmt(setPoint)} °C` : null, p != null ? `power ${Math.round(p * 100)}%` : null].filter(Boolean).join(' · ')}
      </text>
    </svg>
  )
}
