import { useTranslation } from 'react-i18next'
import { Chip } from '@/components/ui/badge'
import { useStore } from '@/store'

export interface GuideSimChipState {
  guiding: boolean
  reason: string | null
}

export function GuideSimChip() {
  const { t } = useTranslation('guide_simulator')
  const s = useStore((st) => st.pluginStates['guide_simulator'] as GuideSimChipState | undefined)
  if (!s) return null
  if (s.guiding) return <Chip label={t('chip.label')} status={t('chip.guiding')} variant="green" />
  if (s.reason === 'stopped' || s.reason === 'disconnected') return null
  return <Chip label={t('chip.label')} status={s.reason ? t(`reason.${s.reason}`, { defaultValue: s.reason.replace('_', ' ') }) : t('chip.lost')} variant="amber" pulse />
}
