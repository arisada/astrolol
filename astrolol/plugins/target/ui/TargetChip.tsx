// Status-bar chip: shows the current mount target name when one is set.
// Reads from pluginStates['target'], updated by the mount.target_set handler in index.ts.

import { Crosshair } from 'lucide-react'
import { useStore } from '@/store'
import { Chip } from '@/components/ui/badge'

interface TargetState {
  name: string | null
  ra: number
  dec: number
}

export function TargetChip() {
  const state = useStore((s) => s.pluginStates['target'] as TargetState | null | undefined)
  if (!state) return null

  const label = state.name ?? `${(state.ra / 15).toFixed(2)}h ${state.dec >= 0 ? '+' : ''}${state.dec.toFixed(1)}°`

  return <Chip icon={<Crosshair className="h-3 w-3 shrink-0 text-slate-500" />} status={label} variant="slate" />
}
