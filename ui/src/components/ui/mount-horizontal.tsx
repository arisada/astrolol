import { equatorialToHorizontal, hourAngle } from '@/utils/sky'

// Mount position on the local sky: centred on the zenith, north up, east to the left, like looking up.
// The RA/Dec grid is drawn on it, so the celestial pole (grey dot) sits at altitude = latitude and
// the grid turns with sidereal time; RA hours are labelled where each line meets the horizon and
// declinations along the north-south axis. The dotted line is the hour circle the mount is on.

const D2R = Math.PI / 180
const C = 60
const RR = 50

export function HorizontalSky({ latitude, lst, ra, dec, label, className = 'w-full' }: {
  latitude: number
  /** Local sidereal time, hours. */
  lst: number
  /** Mount right ascension, hours (same epoch as the LST). */
  ra: number
  /** Mount declination, degrees. */
  dec: number
  label: string
  className?: string
}) {
  const s = latitude < 0 ? -1 : 1
  const tr = (ha: number, d: number) => {
    const { alt, az } = equatorialToHorizontal(latitude, ha, d)
    const r = ((90 - alt) / 90) * RR
    return { alt, x: C - r * Math.sin(az * D2R), y: C - r * Math.cos(az * D2R) }
  }
  const num = (v: number) => v.toFixed(1)
  /** Path of the visible parts of a curve; breaks wherever it dips below the horizon. */
  const path = (pts: { alt: number; x: number; y: number }[]) => {
    let out = ''
    let pen = false
    for (const p of pts) {
      if (p.alt < 0) { pen = false; continue }
      out += `${pen ? 'L' : 'M'}${num(p.x)} ${num(p.y)}`
      pen = true
    }
    return out
  }
  const sign = (d: number) => (d > 0 ? '+' : d < 0 ? '−' : '')

  const decCircles = [60, 30, 0, -30].map((d) => s * d)
  const hours = Array.from({ length: 8 }, (_, i) => i * 3)
  const sweep = (from: number, to: number, step: number) => {
    const out: number[] = []
    for (let v = from; step > 0 ? v <= to : v >= to; v += step) out.push(v)
    return out
  }

  const mountHa = hourAngle(lst, ra)
  const m = tr(mountHa, dec)
  const pole = tr(0, s * 90)
  const meridian = path(sweep(-85, 90, 2).map((d) => tr(mountHa, s * d)))

  return (
    <svg viewBox="-14 -14 148 148" className={className} role="img" aria-label={label}>
      <circle cx={C} cy={C} r={RR} className="fill-none stroke-slate-400" strokeWidth={1.2} vectorEffect="non-scaling-stroke" />
      <circle cx={C} cy={C} r={(RR * 2) / 3} className="fill-none stroke-slate-700" strokeWidth={1} strokeDasharray="1 3" vectorEffect="non-scaling-stroke" />
      <circle cx={C} cy={C} r={RR / 3} className="fill-none stroke-slate-700" strokeWidth={1} strokeDasharray="1 3" vectorEffect="non-scaling-stroke" />
      {decCircles.map((d) => {
        const pts = sweep(0, 360, 5).map((ha) => tr(ha, d))
        const v = tr(0, d)
        return (
          <g key={d}>
            <path d={path(pts)} className="fill-none stroke-slate-700" strokeWidth={1} vectorEffect="non-scaling-stroke" />
            {v.alt > 2 && (
              <text x={v.x + 2} y={v.y + (v.y < C ? -1.5 : 4.5)} className="fill-slate-500 font-mono" fontSize={5}>
                {`${sign(d)}${Math.abs(d)}°`}
              </text>
            )}
          </g>
        )
      })}
      {hours.map((h) => {
        const ha = (lst - h) * 15
        const line = sweep(-85, 90, 0.5).map((d) => tr(ha, s * d))
        // First point (walking from the pole) that is below the horizon: interpolate the crossing.
        const walk = sweep(90, -85, -1).map((d) => tr(ha, s * d))
        let label: { x: number; y: number } | null = null
        for (let i = 1; i < walk.length; i++) {
          if (walk[i].alt < 0 && walk[i - 1].alt >= 0) {
            const k = walk[i - 1].alt / (walk[i - 1].alt - walk[i].alt)
            const x = walk[i - 1].x + (walk[i].x - walk[i - 1].x) * k - C
            const y = walk[i - 1].y + (walk[i].y - walk[i - 1].y) * k - C
            const n = Math.hypot(x, y) || 1
            label = { x: C + (x / n) * (RR + 5), y: C + (y / n) * (RR + 5) }
            break
          }
        }
        return (
          <g key={h}>
            <path d={path(line)} className="fill-none stroke-slate-700" strokeWidth={1} vectorEffect="non-scaling-stroke" />
            {label && <text x={num(label.x)} y={num(label.y + 1.8)} textAnchor="middle" className="fill-slate-500 font-mono" fontSize={5}>{`${h}h`}</text>}
          </g>
        )
      })}
      <path d={meridian} className="fill-none stroke-accent" strokeWidth={1} strokeDasharray="1 2.5" vectorEffect="non-scaling-stroke" />
      <path d="M57 60h6M60 57v6" className="fill-none stroke-slate-400" strokeWidth={1.3} vectorEffect="non-scaling-stroke" />
      <circle cx={pole.x} cy={pole.y} r={2.4} className="fill-slate-500" />
      <circle cx={m.x} cy={m.y} r={3.4} className="fill-accent" />
      <text x={60} y={4} textAnchor="middle" className="fill-slate-500 font-mono" fontSize={7}>{'N'}</text>
      <text x={117} y={62.4} textAnchor="middle" className="fill-slate-500 font-mono" fontSize={7}>{'W'}</text>
      <text x={60} y={120.5} textAnchor="middle" className="fill-slate-500 font-mono" fontSize={7}>{'S'}</text>
      <text x={3} y={62.4} textAnchor="middle" className="fill-slate-500 font-mono" fontSize={7}>{'E'}</text>
    </svg>
  )
}
