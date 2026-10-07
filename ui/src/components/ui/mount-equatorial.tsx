import { hourAngle, horizonCurve } from '@/utils/sky'

// Mount position on the equatorial sky, centred on the visible celestial pole. The RA/Dec grid is
// fixed to the sky, so the horizon (a curve that depends on latitude) turns with sidereal time and
// the mount dot sits at its RA/Dec. The dotted line is the hour circle the mount is on, which keeps
// the position readable close to the pole. Everything is computed from the props; it scales to its
// parent (give it a width via className).

const D2R = Math.PI / 180
const C = 60
const RIM = 52

export function EquatorialSky({ latitude, lst, ra, dec, label, className = 'w-full' }: {
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
  // The horizon reaches 90° + |latitude| from the pole; always show at least 135°.
  const range = Math.max(135, 180 - Math.abs(latitude) + 3)
  const K = RIM / range
  const L = lst * 15
  /** Chart position of a point given its angle round the pole (HA − LST, degrees) and declination. */
  const P = (a: number, d: number, extra = 0): [number, number] => {
    const r = (90 - s * d) * K + extra
    return [C - s * r * Math.sin(a * D2R), C - r * Math.cos(a * D2R)]
  }
  const num = (v: number) => v.toFixed(1)
  const sign = (d: number) => (d > 0 ? '+' : d < 0 ? '−' : '')

  const decCircles = [60, 30, 0, -30].map((d) => s * d)
  const hours = Array.from({ length: 8 }, (_, i) => i * 3)

  const horizon = horizonCurve(latitude)
    .map((p, i) => { const [x, y] = P(p.ha - L, p.dec); return `${i ? 'L' : 'M'}${num(x)} ${num(y)}` })
    .join('')
  const a = hourAngle(lst, ra) - L   // = −RA·15 (mod 360)
  const [mx, my] = P(a, dec)
  const [zx, zy] = P(-L, latitude)
  const rimX = C - s * RIM * Math.sin(a * D2R)
  const rimY = C - RIM * Math.cos(a * D2R)

  return (
    <svg viewBox="-14 -14 148 148" className={className} role="img" aria-label={label}>
      <circle cx={C} cy={C} r={RIM} className="fill-none stroke-slate-700" strokeWidth={1} vectorEffect="non-scaling-stroke" />
      {decCircles.map((d) => (
        <g key={d}>
          <circle cx={C} cy={C} r={(90 - s * d) * K} className="fill-none stroke-slate-700" strokeWidth={1} vectorEffect="non-scaling-stroke" />
          <text x={C + 2} y={C + (90 - s * d) * K + 6.5} className="fill-slate-500 font-mono" fontSize={6.5}>
            {`${sign(d)}${Math.abs(d)}°`}
          </text>
        </g>
      ))}
      {hours.map((h) => {
        const [x1, y1] = P(-h * 15, s * 87)
        const [x2, y2] = P(-h * 15, -s * (range - 90))
        const [lx, ly] = P(-h * 15, -s * (range - 90), 6)
        return (
          <g key={h}>
            <path d={`M${num(x1)} ${num(y1)}L${num(x2)} ${num(y2)}`} className="stroke-slate-700" strokeWidth={1} vectorEffect="non-scaling-stroke" />
            <text x={lx} y={ly + 2} textAnchor="middle" className="fill-slate-500 font-mono" fontSize={7}>{`${h}h`}</text>
          </g>
        )
      })}
      {/* Below the horizon: shaded; the horizon itself is the bright curve. */}
      <path d={`M${C - RIM} ${C}a${RIM} ${RIM} 0 1 0 ${2 * RIM} 0a${RIM} ${RIM} 0 1 0 ${-2 * RIM} 0Z${horizon}Z`}
        className="fill-slate-500/15" fillRule="evenodd" />
      <path d={`${horizon}Z`} className="fill-none stroke-slate-400" strokeWidth={1.2} vectorEffect="non-scaling-stroke" />
      <path d={`M${C} ${C}L${num(rimX)} ${num(rimY)}`} className="stroke-accent" strokeWidth={1} strokeDasharray="1 2.5" vectorEffect="non-scaling-stroke" />
      <circle cx={C} cy={C} r={2.4} className="fill-slate-500" />
      <path d={`M${num(zx - 3)} ${num(zy)}h6M${num(zx)} ${num(zy - 3)}v6`} className="stroke-slate-400" strokeWidth={1.3} vectorEffect="non-scaling-stroke" />
      <circle cx={mx} cy={my} r={3.4} className="fill-accent" />
    </svg>
  )
}
