import { useTranslation } from 'react-i18next'
import { useStore } from '@/store'
import { Chip } from '@/components/ui/badge'

interface PolarAlignRunningState {
  status: 'running' | 'converging'
  pointIndex: number | null
  altErrorArcmin: number | null
  azErrorArcmin: number | null
}

export function PolarAlignChip() {
  const { t } = useTranslation('polar_align')
  const run = useStore((s) => s.pluginStates['polar_align'] as PolarAlignRunningState | null | undefined)
  if (!run) return null

  if (run.status === 'running') {
    const progress = run.pointIndex !== null ? t('chip.point', { index: run.pointIndex + 1 }) : ''
    return <Chip label={t('chip.label')} status={t('chip.fitting', { progress })} variant="violet" pulse />
  }

  const err = run.altErrorArcmin !== null && run.azErrorArcmin !== null
    ? ` ${run.altErrorArcmin >= 0 ? '+' : ''}${run.altErrorArcmin.toFixed(1)}'${t('chip.alt')} / ${run.azErrorArcmin >= 0 ? '+' : ''}${run.azErrorArcmin.toFixed(1)}'${t('chip.az')}`
    : ''
  return <Chip label={t('chip.label')} status={t('chip.converging', { err })} variant="amber" pulse />
}
