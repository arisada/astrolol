import { useTranslation } from 'react-i18next'
import { Chip, type ChipVariant } from '@/components/ui/badge'
import { useSequencer } from './state'
import { activityLabel } from './format'

export function SequencerChip() {
  const { t } = useTranslation('sequencer')
  const { status } = useSequencer()
  if (!status || status.run_state === 'idle') return null

  const current = status.current
  const label = current ? current.name : t('chip.label')

  let text: string
  let variant: ChipVariant
  let pulse = false
  switch (status.run_state) {
    case 'paused':
      text = status.pause_reason && status.pause_reason !== 'user' ? t('chip.pausedError') : t('chip.paused')
      variant = status.pause_reason && status.pause_reason !== 'user' ? 'red' : 'amber'
      break
    case 'pausing':
    case 'stopping':
      text = status.run_state === 'pausing' ? t('chip.pausing') : t('chip.stopping')
      variant = 'amber'
      pulse = true
      break
    default: {
      const activity = status.activity
      if (activity === 'exposing' && current && current.group_count != null && status.lanes[0]?.current_group != null) {
        const done = status.lanes[0].groups[status.lanes[0].current_group]?.frames_done ?? 0
        text = `${current.filter_name ? `${current.filter_name} ` : ''}${done + 1}/${current.group_count}`
        variant = 'blue'
      } else {
        text = activity ? activityLabel(activity) : t('chip.running')
        variant = activity === 'centering' ? 'violet' : 'amber'
      }
      pulse = true
    }
  }
  return <Chip label={label} status={text} variant={variant} pulse={pulse} />
}
