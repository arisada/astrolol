import { niceTicks } from '@/utils/sky'

// Focuser position on a graduated ruler. ▼ filled = current position, ▽ outline = target (while
// moving), ▽ dotted = the position a run started from (e.g. autofocus). The caller picks the visible
// window (min..max): the whole travel, or a range around the working position.

const W = 300
const PAD = 18

function Marker({ x, kind }: { x: number; kind: 'position' | 'target' | 'initial' }) {
  const d = `M${x} 21l-4 -9h8z`
  if (kind === 'position') return <path d={d} className="fill-accent" />
  return (
    <path d={d} fill="none" strokeWidth={1.3} vectorEffect="non-scaling-stroke"
      className={kind === 'target' ? 'stroke-accent' : 'stroke-slate-400'}
      strokeDasharray={kind === 'initial' ? '1.5 1.5' : undefined} />
  )
}

export function FocuserRuler({ position, target, initial, min, max, label, className = 'w-full' }: {
  position: number
  target?: number | null
  /** Optional: where the run started, shown as a dotted marker. */
  initial?: number | null
  min: number
  max: number
  label: string
  className?: string
}) {
  const x = (v: number) => PAD + ((Math.min(max, Math.max(min, v)) - min) / (max - min)) * (W - 2 * PAD)
  const { major, minor } = niceTicks(min, max, 5)
  // Label every other major tick when they would crowd each other.
  const labelEvery = major.length > 6 ? 2 : 1

  return (
    <svg viewBox="0 0 300 44" className={className} role="img" aria-label={label}>
      <path d={`M${PAD} 22H${W - PAD}`} className="stroke-surface-border" vectorEffect="non-scaling-stroke" />
      {minor.map((v) => <path key={`n${v}`} d={`M${x(v)} 22v3.5`} className="stroke-surface-border" strokeWidth={1} vectorEffect="non-scaling-stroke" />)}
      {major.map((v, i) => (
        <g key={`m${v}`}>
          <path d={`M${x(v)} 22v7`} className="stroke-slate-500" strokeWidth={1} vectorEffect="non-scaling-stroke" />
          {i % labelEvery === 0 && (
            <text x={x(v)} y={39} textAnchor="middle" className="fill-slate-500 font-mono" fontSize={7}>{v}</text>
          )}
        </g>
      ))}
      {initial != null && <Marker x={x(initial)} kind="initial" />}
      {target != null && <Marker x={x(target)} kind="target" />}
      <Marker x={x(position)} kind="position" />
    </svg>
  )
}
