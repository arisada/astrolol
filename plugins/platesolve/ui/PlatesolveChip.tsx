import { useStore } from '@/store'
import { Chip } from '@/components/StatusBar'
import type { PlateSolvePluginState } from './api'

export function PlatesolveChip() {
  const jobs = useStore((s) => (s.pluginStates['platesolve'] as PlateSolvePluginState | null | undefined)?.jobs ?? {})
  const active = Object.values(jobs).find(
    (j) => j.status === 'pending' || j.status === 'exposing' || j.status === 'solving',
  )
  if (!active) return null

  const status = active.status === 'solving' ? 'Solving' : 'Exposing'
  return <Chip label="Plate Solve" status={status} variant="violet" pulse />
}
