import { useTranslation } from 'react-i18next'
import { Chip, type ChipVariant } from '@/components/ui/badge'
import { useSequencer } from './state'
import { activityLabel } from './format'

export function SequencerChip() {
  const { t } = useTranslation('sequencer')
  const { status, entries } = useSequencer()
  if (!status || status.run_state === 'idle') return null

  const current = entries?.find((e) => e.task.id === status.current_task_id)
  const label = current ? current.task.name || current.task.target.name : t('chip.label')

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
      if (activity === 'exposing' && current && status.lanes[0]?.current_group != null) {
        const gi = status.lanes[0].current_group
        const g = current.task.lanes[0].groups[gi]
        const done = status.lanes[0].groups[gi]?.frames_done ?? 0
        text = `${g.filter_name ? `${g.filter_name} ` : ''}${done + 1}/${g.count}`
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
