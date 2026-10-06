import { useTranslation } from 'react-i18next'
import { useStore } from '@/store'
import { Chip } from '@/components/ui/badge'

interface AutofocusRunningState {
  runId: string
  step: number
  totalSteps: number
  fwhm: number | null
}

export function AutofocusChip() {
  const { t } = useTranslation('autofocus')
  const af = useStore((s) => s.pluginStates['autofocus'] as AutofocusRunningState | null | undefined)
  if (!af) return null

  const progress = af.totalSteps > 0 ? ` ${af.step}/${af.totalSteps}` : ''
  const fwhm = af.fwhm !== null && af.fwhm > 0 ? ` · ${af.fwhm.toFixed(1)}px` : ''

  return <Chip label={t('chip.label')} status={t('chip.step', { progress, fwhm })} variant="amber" pulse />
}
