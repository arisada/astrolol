import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { fmtArcmin, knobMove } from './angle'
import type { ArrowDirection } from './angle'

const ICONS: Record<ArrowDirection, LucideIcon> = {
  up: ArrowUp, down: ArrowDown, left: ArrowLeft, right: ArrowRight,
}

// Below this the remaining error is within what the knobs can set; the arrow is dimmed.
const NEGLIGIBLE_ARCMIN = 0.5

function Arrow({ direction, arcmin, label }: { direction: ArrowDirection; arcmin: number; label: string }) {
  const Icon = ICONS[direction]
  const quiet = arcmin < NEGLIGIBLE_ARCMIN
  return (
    <div className={`flex items-center gap-1.5 ${quiet ? 'text-slate-600' : 'text-amber-300'}`} title={label} aria-label={label}>
      <Icon size={22} strokeWidth={2.25} />
      <span className="font-mono text-sm tabular-nums">{fmtArcmin(arcmin)}</span>
    </div>
  )
}

/**
 * The move still needed, as one vertical and one horizontal arrow with the angle next to each:
 * the altitude knob goes up or down, the azimuth knob left or right (facing the pole).
 */
export function KnobArrows({ altErrorArcmin, azErrorArcmin, altLabel, azLabel }: {
  altErrorArcmin: number
  azErrorArcmin: number
  altLabel: string
  azLabel: string
}) {
  const move = knobMove(altErrorArcmin, azErrorArcmin)
  return (
    <div className="grid grid-cols-2 gap-3">
      <div className="flex flex-col gap-1">
        <span className="label-caps text-slate-500">{altLabel}</span>
        <Arrow direction={move.vertical.direction} arcmin={move.vertical.arcmin} label={altLabel} />
      </div>
      <div className="flex flex-col gap-1">
        <span className="label-caps text-slate-500">{azLabel}</span>
        <Arrow direction={move.horizontal.direction} arcmin={move.horizontal.arcmin} label={azLabel} />
      </div>
    </div>
  )
}
