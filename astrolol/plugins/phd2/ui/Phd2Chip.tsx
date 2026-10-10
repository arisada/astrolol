import { useTranslation } from 'react-i18next'
import { useStore } from '@/store'
import { Chip } from '@/components/ui/badge'
import type { Phd2PluginState } from './api'

export function Phd2Chip() {
  const { t } = useTranslation('phd2')
  const phd2 = useStore((s) => (s.pluginStates['phd2'] as Phd2PluginState | null | undefined)?.status)
  if (!phd2?.connected) return null

  const state = phd2.state ?? ''
  const rms = phd2.rms_total

  if (state === 'Guiding') {
    const rmsStr = rms !== null ? ` ${rms.toFixed(2)}"` : ''
    return <Chip label="PHD2" status={t('chip.guiding', { rms: rmsStr })} variant="green" />
  }
  if (state === 'Calibrating') {
    return <Chip label="PHD2" status={t('chip.calibrating')} variant="amber" pulse />
  }
  if (phd2.is_dithering) {
    return <Chip label="PHD2" status={t('chip.dithering')} variant="amber" pulse />
  }
  if (state && state !== 'Stopped' && state !== 'Disconnected' && state !== 'Unknown') {
    return <Chip label="PHD2" status={t(`state.${state.toLowerCase().replace(' ', '_')}`, { defaultValue: state })} variant="slate" />
  }
  return <Chip label="PHD2" status={t('chip.connected')} variant="slate" />
}
