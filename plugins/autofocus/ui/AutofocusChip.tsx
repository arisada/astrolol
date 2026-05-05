import { useStore } from '@/store'
import { Chip } from '@/components/ui/badge'

interface AutofocusRunningState {
  runId: string
  step: number
  totalSteps: number
  fwhm: number | null
}

export function AutofocusChip() {
  const af = useStore((s) => s.pluginStates['autofocus'] as AutofocusRunningState | null | undefined)
  if (!af) return null

  const progress = af.totalSteps > 0 ? ` ${af.step}/${af.totalSteps}` : ''
  const fwhm = af.fwhm !== null && af.fwhm > 0 ? ` · ${af.fwhm.toFixed(1)}px` : ''

  return <Chip label="Autofocus" status={`Step${progress}${fwhm}`} variant="amber" pulse />
}
