import { useTranslation } from 'react-i18next'
import { useStore } from '@/store'
import { Chip } from '@/components/ui/badge'
import type { PlateSolvePluginState } from './api'

export function PlatesolveChip() {
  const { t } = useTranslation('platesolve')
  const jobs = useStore((s) => (s.pluginStates['platesolve'] as PlateSolvePluginState | null | undefined)?.jobs ?? {})
  const active = Object.values(jobs).find(
    (j) => j.status === 'pending' || j.status === 'exposing' || j.status === 'solving',
  )
  if (!active) return null

  const status = active.status === 'solving' ? t('chip.solving') : t('chip.exposing')
  return <Chip label={t('chip.label')} status={status} variant="violet" pulse />
}
