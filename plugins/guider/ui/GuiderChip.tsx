import { useTranslation } from 'react-i18next'
import { Chip } from '@/components/ui/badge'
import { useStore } from '@/store'
import type { GuiderChipState } from './api'

export function GuiderChip() {
  const { t } = useTranslation('guider')
  const s = useStore((st) => st.pluginStates['guider'] as GuiderChipState | undefined)
  if (!s) return null
  if (s.guiding) return <Chip label={t('chip.label')} status={t('chip.guiding')} variant="green" />
  if (s.reason === 'stopped' || s.reason === 'disconnected') return null
  return (
    <Chip
      label={t('chip.label')}
      status={s.reason ? t(`reason.${s.reason}`, { defaultValue: s.reason.replace('_', ' ') }) : t('chip.lost')}
      variant="amber"
      pulse
    />
  )
}
