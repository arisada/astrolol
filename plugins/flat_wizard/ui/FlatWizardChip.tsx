import { useStore } from '@/store'
import { Chip } from '@/components/ui/badge'
import type { FlatWizardLiveState } from './state'

export function FlatWizardChip() {
  const fw = useStore((s) => s.pluginStates['flat_wizard'] as FlatWizardLiveState | null | undefined)
  if (!fw) return null

  // Cameras are solved concurrently, so progress is "combinations finished", and the
  // latest trial can come from any camera.
  const last = fw.trials[fw.trials.length - 1]
  const progress = fw.totalFilters > 0 ? `${fw.liveResults.length}/${fw.totalFilters}` : ''
  const latest = last
    ? ` · ${last.filterName ?? last.cameraId} ${last.ratioPct.toFixed(0)}%${last.saturated ? ' (sat)' : ''}`
    : ''

  return <Chip label="Flats" status={`${progress}${latest}`} variant="violet" pulse />
}
