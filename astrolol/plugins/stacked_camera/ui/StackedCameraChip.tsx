import { useTranslation } from 'react-i18next'
import { Chip } from '@/components/ui/badge'
import { useStore } from '@/store'
import type { StackProgressState } from './progress'

export function StackedCameraChip() {
  const { t } = useTranslation('stacked_camera')
  const progress = useStore((s) => s.pluginStates['stacked_camera'] as StackProgressState | null | undefined)
  const running = Object.values(progress ?? {})
  if (running.length === 0) return null
  const first = running[0]
  const status = t('chip.progress', { done: Math.round(first.exposureDone), total: Math.round(first.exposureTotal) })
  return <Chip label={t('chip.label')} status={status} variant="blue" pulse />
}
