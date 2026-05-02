// Status-bar chip: shows the current mount target name when one is set.
// Reads from pluginStates['target'], updated by the mount.target_set handler in index.ts.

import { Crosshair } from 'lucide-react'
import { useStore } from '@/store'

interface TargetState {
  name: string | null
  ra: number
  dec: number
}

export function TargetChip() {
  const state = useStore((s) => s.pluginStates['target'] as TargetState | null | undefined)
  if (!state) return null

  const label = state.name ?? `${(state.ra / 15).toFixed(2)}h ${state.dec >= 0 ? '+' : ''}${state.dec.toFixed(1)}°`

  return (
    <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded border text-xs font-medium whitespace-nowrap bg-slate-700/50 text-slate-400 border-slate-600/40">
      <Crosshair className="h-3 w-3 shrink-0" />
      <span className="text-slate-500 truncate max-w-[8rem]">{label}</span>
    </span>
  )
}
