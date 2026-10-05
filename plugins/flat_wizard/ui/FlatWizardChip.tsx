import { useStore } from '@/store'
import { Chip } from '@/components/ui/badge'
import type { FlatWizardLiveState } from './state'

export function FlatWizardChip() {
  const fw = useStore((s) => s.pluginStates['flat_wizard'] as FlatWizardLiveState | null | undefined)
  if (!fw) return null

  const last = fw.trials[fw.trials.length - 1]
  const filter = last?.filterName ?? 'single pass'
  const progress = fw.totalFilters > 0 ? ` ${(last?.filterIndex ?? 0) + 1}/${fw.totalFilters}` : ''
  const ratio = last ? ` · ${last.ratioPct.toFixed(0)}%${last.saturated ? ' (sat)' : ''}` : ''

  return <Chip label="Flats" status={`${filter}${progress}${ratio}`} variant="violet" pulse />
}
