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

/** Small triangle matching the ruler markers, for legends. */
function Swatch({ kind }: { kind: 'position' | 'target' | 'initial' }) {
  return (
    <svg width="11" height="10" viewBox="0 0 11 10" className="inline-block shrink-0 align-[-1px]" aria-hidden>
      <path d="M1 1h9L5.5 9z" strokeWidth={1.3}
        className={kind === 'position' ? 'fill-accent stroke-accent' : kind === 'target' ? 'fill-none stroke-accent' : 'fill-none stroke-slate-400'}
        strokeDasharray={kind === 'initial' ? '1.5 1.5' : undefined} />
    </svg>
  )
}

export function FocuserRuler({ position, target, initial, min, max, label, legend, className = 'w-full' }: {
  position: number
  target?: number | null
  /** Optional: where the run started, shown as a dotted marker. */
  initial?: number | null
  min: number
  max: number
  label: string
  /** Optional legend, one entry per marker that has text (already formatted and translated). */
  legend?: { position?: string; target?: string; initial?: string }
  className?: string
}) {
  const x = (v: number) => PAD + ((Math.min(max, Math.max(min, v)) - min) / (max - min)) * (W - 2 * PAD)
  const { major, minor } = niceTicks(min, max, 5)
  // Label every other major tick when they would crowd each other.
  const labelEvery = major.length > 6 ? 2 : 1

  return (
    <div className={className}>
    <svg viewBox="0 0 300 44" className="w-full" role="img" aria-label={label}>
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
    {legend && (
      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 font-mono text-[11px] text-slate-400">
        {legend.position && <span className="inline-flex items-center gap-1"><Swatch kind="position" />{legend.position}</span>}
        {legend.target && <span className="inline-flex items-center gap-1"><Swatch kind="target" />{legend.target}</span>}
        {legend.initial && <span className="inline-flex items-center gap-1"><Swatch kind="initial" />{legend.initial}</span>}
      </div>
    )}
    </div>
  )
}
