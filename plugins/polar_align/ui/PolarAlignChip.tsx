import { useStore } from '@/store'
import { Chip } from '@/components/ui/badge'

interface PolarAlignRunningState {
  status: 'running' | 'converging'
  pointIndex: number | null
  altErrorArcmin: number | null
  azErrorArcmin: number | null
}

export function PolarAlignChip() {
  const run = useStore((s) => s.pluginStates['polar_align'] as PolarAlignRunningState | null | undefined)
  if (!run) return null

  if (run.status === 'running') {
    const progress = run.pointIndex !== null ? ` point ${run.pointIndex + 1}/3` : ''
    return <Chip label="Polar Align" status={`Fitting${progress}`} variant="violet" pulse />
  }

  const err = run.altErrorArcmin !== null && run.azErrorArcmin !== null
    ? ` ${run.altErrorArcmin >= 0 ? '+' : ''}${run.altErrorArcmin.toFixed(1)}'alt / ${run.azErrorArcmin >= 0 ? '+' : ''}${run.azErrorArcmin.toFixed(1)}'az`
    : ''
  return <Chip label="Polar Align" status={`Converging${err}`} variant="amber" pulse />
}
