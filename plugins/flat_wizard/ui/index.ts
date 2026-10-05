import { Sun } from 'lucide-react'
import { FlatWizardPage } from './FlatWizardPage'
import { FlatWizardChip } from './FlatWizardChip'
import { registerPluginEventHandlers } from '@/store'
import type { AstrolollEvent } from '@/api/types'
import type { FlatWizardLiveState } from './state'

registerPluginEventHandlers('flat_wizard', {
  'flat_wizard.started': (event: AstrolollEvent) => {
    const e = event as Extract<AstrolollEvent, { type: 'flat_wizard.started' }>
    return { totalFilters: e.total_filters, trials: [], liveResults: [] } satisfies FlatWizardLiveState
  },
  'flat_wizard.trial': (event: AstrolollEvent, cur: unknown) => {
    const e = event as Extract<AstrolollEvent, { type: 'flat_wizard.trial' }>
    const current = (cur as FlatWizardLiveState | null | undefined) ?? { totalFilters: e.filter_index + 1, trials: [], liveResults: [] }
    const trial = {
      filterIndex: e.filter_index, filterName: e.filter_name, attempt: e.attempt,
      duration: e.duration, meanAdu: e.mean_adu, fullScaleAdu: e.full_scale_adu,
      ratioPct: e.ratio_pct, saturated: e.saturated,
    }
    // Bounded so a slow-to-converge run (lots of filters/attempts) doesn't grow forever.
    const trials = [...current.trials, trial].slice(-100)
    return { ...current, trials } satisfies FlatWizardLiveState
  },
  'flat_wizard.filter_solved': (event: AstrolollEvent, cur: unknown) => {
    const e = event as Extract<AstrolollEvent, { type: 'flat_wizard.filter_solved' }>
    const current = (cur as FlatWizardLiveState | null | undefined) ?? { totalFilters: e.filter_index + 1, trials: [], liveResults: [] }
    return {
      ...current,
      liveResults: [...current.liveResults, { filterIndex: e.filter_index, filterName: e.filter_name, status: 'solved' as const, duration: e.duration }],
    } satisfies FlatWizardLiveState
  },
  'flat_wizard.filter_failed': (event: AstrolollEvent, cur: unknown) => {
    const e = event as Extract<AstrolollEvent, { type: 'flat_wizard.filter_failed' }>
    const current = (cur as FlatWizardLiveState | null | undefined) ?? { totalFilters: e.filter_index + 1, trials: [], liveResults: [] }
    return {
      ...current,
      liveResults: [...current.liveResults, { filterIndex: e.filter_index, filterName: e.filter_name, status: 'failed' as const, error: e.error }],
    } satisfies FlatWizardLiveState
  },
  'flat_wizard.completed': () => null,
  'flat_wizard.failed': () => null,
  'flat_wizard.aborted': () => null,
})

export default {
  icon: Sun,
  label: 'Flat Wizard',
  Component: FlatWizardPage,
  StatusChip: FlatWizardChip,
}
