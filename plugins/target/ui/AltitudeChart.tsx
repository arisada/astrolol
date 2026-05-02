// Pure-SVG altitude chart. No charting library dependency.
// X-axis: dark hours only (astronomical dusk → astronomical dawn, rounded to :30).
// Y-axis: -10° to 90°.
// Shows twilight shading, min-altitude line, rise/transit/set markers, altitude curve.

import type { AltitudePoint, EphemerisResult } from './api'

interface Props {
  ephemeris: EphemerisResult
  minAlt: number
}

const W = 600
const H = 200
const PAD = { top: 12, right: 16, bottom: 30, left: 36 }
const CHART_W = W - PAD.left - PAD.right
const CHART_H = H - PAD.top - PAD.bottom

const Y_MIN = -10   // degrees — bottom of chart
const Y_MAX = 90    // degrees — top of chart
const Y_RANGE = Y_MAX - Y_MIN

const HALF_HOUR_MS = 30 * 60 * 1000

function floorHalfHour(ms: number): number {
  return Math.floor(ms / HALF_HOUR_MS) * HALF_HOUR_MS
}

function ceilHalfHour(ms: number): number {
  return Math.ceil(ms / HALF_HOUR_MS) * HALF_HOUR_MS
}

const EXTEND_MS = HALF_HOUR_MS  // 30-min padding on each side of the dark window

/** Determine the chart domain: civil dusk − 30 min → civil dawn + 30 min, rounded to :30.
 *  Falls back to nautical then astronomical if civil times are unavailable. */
function chartDomain(ephemeris: EphemerisResult): [number, number] {
  const tw = ephemeris.twilight
  const dusk = tw.civil_dusk ?? tw.nautical_dusk ?? tw.astronomical_dusk
  const dawn = tw.civil_dawn ?? tw.nautical_dawn ?? tw.astronomical_dawn

  const curve = ephemeris.altitude_curve
  if (curve.length === 0) return [0, 1]

  const curveStart = new Date(curve[0].time).getTime()
  const curveEnd = new Date(curve[curve.length - 1].time).getTime()

  const t0 = dusk ? floorHalfHour(new Date(dusk).getTime() - EXTEND_MS) : curveStart
  const t1 = dawn ? ceilHalfHour(new Date(dawn).getTime() + EXTEND_MS) : curveEnd

  // Clamp to the curve's actual range
  return [Math.max(t0, curveStart), Math.min(t1, curveEnd)]
}

function toX(ms: number, domain: [number, number]): number {
  return PAD.left + ((ms - domain[0]) / (domain[1] - domain[0])) * CHART_W
}

function toY(alt: number): number {
  const pct = (alt - Y_MIN) / Y_RANGE
  return PAD.top + CHART_H - pct * CHART_H
}

function isoToMs(iso: string): number {
  return new Date(iso).getTime()
}

function formatHour(ms: number): string {
  const d = new Date(ms)
  const h = d.getHours().toString().padStart(2, '0')
  const m = d.getMinutes().toString().padStart(2, '0')
  return `${h}:${m}`
}

function vMarker(
  iso: string | null,
  domain: [number, number],
  color: string,
  label: string,
  key: string,
): React.ReactNode {
  if (!iso) return null
  const ms = isoToMs(iso)
  if (ms < domain[0] || ms > domain[1]) return null
  const x = toX(ms, domain)
  return (
    <g key={key}>
      <line x1={x} y1={PAD.top} x2={x} y2={PAD.top + CHART_H} stroke={color} strokeWidth={1} strokeDasharray="3 3" opacity={0.8} />
      <text x={x + 3} y={PAD.top + 10} fill={color} fontSize={9} opacity={0.9}>{label}</text>
      <text x={x + 3} y={PAD.top + 19} fill={color} fontSize={8} opacity={0.7}>{formatHour(ms)}</text>
    </g>
  )
}

export function AltitudeChart({ ephemeris, minAlt }: Props) {
  const { altitude_curve, twilight, rise, transit, set, peak_time } = ephemeris

  if (altitude_curve.length === 0) return null

  const domain = chartDomain(ephemeris)

  // Filter curve to domain, build polyline points
  const visiblePoints = altitude_curve.filter((p: AltitudePoint) => {
    const ms = isoToMs(p.time)
    return ms >= domain[0] && ms <= domain[1]
  })

  const points = visiblePoints
    .map((p: AltitudePoint) => `${toX(isoToMs(p.time), domain).toFixed(1)},${toY(p.alt).toFixed(1)}`)
    .join(' ')

  // Horizon (0°) and min-altitude lines
  const y0   = toY(0)
  const yMin = toY(minAlt)

  // Shade area under the curve (clipped above Y_MIN)
  const areaPoints = [
    `${toX(domain[0], domain).toFixed(1)},${toY(Y_MIN).toFixed(1)}`,
    ...visiblePoints.map((p: AltitudePoint) =>
      `${toX(isoToMs(p.time), domain).toFixed(1)},${toY(Math.max(p.alt, Y_MIN)).toFixed(1)}`
    ),
    `${toX(domain[1], domain).toFixed(1)},${toY(Y_MIN).toFixed(1)}`,
  ].join(' ')

  // Twilight bands (applied left-to-right, darkest first)
  function band(start: string | null, end: string | null, fill: string, key: string) {
    if (!start || !end) return null
    const x1 = Math.max(PAD.left, toX(isoToMs(start), domain))
    const x2 = Math.min(PAD.left + CHART_W, toX(isoToMs(end), domain))
    if (x2 <= x1) return null
    return <rect key={key} x={x1} y={PAD.top} width={x2 - x1} height={CHART_H} fill={fill} />
  }

  // X-axis ticks at every :00 and :30 within the domain
  const tickMs: number[] = []
  for (let t = ceilHalfHour(domain[0]); t <= domain[1]; t += HALF_HOUR_MS) {
    tickMs.push(t)
  }
  // Show every other tick label if ticks are dense
  const tickInterval = tickMs.length > 12 ? 2 : 1

  // Y-axis grid lines
  const yGridAlts = [0, 30, 60, 90].filter((a) => a >= Y_MIN)

  const clipId = 'chart-clip'

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="w-full rounded-lg bg-slate-900/60"
      style={{ maxHeight: 200 }}
    >
      <defs>
        {/* Clip everything to the chart area so the curve never bleeds outside */}
        <clipPath id={clipId}>
          <rect x={PAD.left} y={PAD.top} width={CHART_W} height={CHART_H} />
        </clipPath>
      </defs>

      {/* Background: full chart = daytime colour */}
      <rect x={PAD.left} y={PAD.top} width={CHART_W} height={CHART_H} fill="rgba(251,191,36,0.04)" />

      {/* Civil twilight: civil_dusk → civil_dawn */}
      {band(twilight.civil_dusk, twilight.civil_dawn, 'rgba(30,41,59,0.55)', 'civil')}

      {/* Nautical twilight */}
      {band(twilight.nautical_dusk, twilight.nautical_dawn, 'rgba(15,23,42,0.55)', 'nautical')}

      {/* Astronomical night */}
      {band(twilight.astronomical_dusk, twilight.astronomical_dawn, 'rgba(2,6,23,0.65)', 'astro')}

      {/* Y-axis grid */}
      {yGridAlts.map((alt) => (
        <g key={`grid-${alt}`}>
          <line
            x1={PAD.left} y1={toY(alt)}
            x2={PAD.left + CHART_W} y2={toY(alt)}
            stroke="rgba(100,116,139,0.2)" strokeWidth={1}
          />
          <text x={PAD.left - 4} y={toY(alt) + 3} fill="rgba(148,163,184,0.55)" fontSize={8} textAnchor="end">{alt}°</text>
        </g>
      ))}

      {/* Horizon line */}
      <line x1={PAD.left} y1={y0} x2={PAD.left + CHART_W} y2={y0}
        stroke="rgba(100,116,139,0.45)" strokeWidth={1} />

      {/* Min-altitude dashed line */}
      <line x1={PAD.left} y1={yMin} x2={PAD.left + CHART_W} y2={yMin}
        stroke="rgba(251,146,60,0.5)" strokeWidth={1} strokeDasharray="4 3" />

      {/* Filled area + curve — clipped to chart bounds */}
      <g clipPath={`url(#${clipId})`}>
        <polygon points={areaPoints} fill="rgba(99,102,241,0.12)" />
        {visiblePoints.length > 1 && (
          <polyline
            points={points}
            fill="none"
            stroke="rgb(99,102,241)"
            strokeWidth={2}
            strokeLinejoin="round"
          />
        )}
      </g>

      {/* Rise / transit / set markers — clipped so labels stay inside */}
      <g clipPath={`url(#${clipId})`}>
        {vMarker(rise,                domain, 'rgb(74,222,128)',  'Rise',    'rise')}
        {vMarker(transit ?? peak_time, domain, 'rgb(250,204,21)', 'Transit', 'transit')}
        {vMarker(set,                 domain, 'rgb(248,113,113)', 'Set',     'set')}
      </g>

      {/* X-axis ticks */}
      {tickMs.map((ms, i) => {
        const x = toX(ms, domain)
        const showLabel = i % tickInterval === 0
        return (
          <g key={ms}>
            <line x1={x} y1={PAD.top + CHART_H} x2={x} y2={PAD.top + CHART_H + 3}
              stroke="rgba(100,116,139,0.4)" strokeWidth={1} />
            {showLabel && (
              <text x={x} y={PAD.top + CHART_H + 12} fill="rgba(148,163,184,0.55)" fontSize={8} textAnchor="middle">
                {formatHour(ms)}
              </text>
            )}
          </g>
        )
      })}

      {/* Chart border */}
      <rect x={PAD.left} y={PAD.top} width={CHART_W} height={CHART_H}
        fill="none" stroke="rgba(100,116,139,0.2)" strokeWidth={1} />
    </svg>
  )
}
