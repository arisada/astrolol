import { Focus } from 'lucide-react'
import { AutofocusPage } from './AutofocusPage'
import { AutofocusChip } from './AutofocusChip'
import { registerPluginEventHandlers } from '@/store'
import type { AstrolollEvent } from '@/api/types'

interface AutofocusRunningState {
  runId: string
  step: number
  totalSteps: number
  fwhm: number | null
}

// Register autofocus event handlers with the core store.
// Called once at module load (eager import in plugin-registry.ts).
registerPluginEventHandlers('autofocus', {
  'autofocus.started': (event: AstrolollEvent) => {
    const e = event as Extract<AstrolollEvent, { type: 'autofocus.started' }>
    return { runId: e.run_id, step: 0, totalSteps: e.total_steps, fwhm: null } satisfies AutofocusRunningState
  },
  'autofocus.data_point': (event: AstrolollEvent, cur: unknown) => {
    const e = event as Extract<AstrolollEvent, { type: 'autofocus.data_point' }>
    const current = cur as AutofocusRunningState | null | undefined
    return current
      ? { ...current, step: e.step, totalSteps: e.total_steps, fwhm: e.fwhm }
      : { runId: e.run_id, step: e.step, totalSteps: e.total_steps, fwhm: e.fwhm }
  },
  'autofocus.completed': () => null,
  'autofocus.aborted': () => null,
  'autofocus.failed': () => null,
})

export default {
  icon: Focus,
  label: 'Autofocus',
  Component: AutofocusPage,
  StatusChip: AutofocusChip,
}
