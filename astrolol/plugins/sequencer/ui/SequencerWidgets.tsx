// Sequencer read-out for the dock: what the run is doing and how far along it is.
import { useTranslation } from 'react-i18next'
import { ProgressBar } from '@/components/ui/progress-bar'
import { StatusPill, type StatusPillVariant } from '@/components/ui/badge'
import { activityLabel, fmtSeconds, taskName, taskProgress } from './format'
import { useSequencer } from './state'

export function SequencerProgressWidget() {
  const { t } = useTranslation('sequencer')
  const { status, entries } = useSequencer()
  if (!status || status.run_state === 'idle') {
    return <p className="text-xs text-slate-500">{t('widget.idle')}</p>
  }

  const current = entries?.find((e) => e.task.id === status.current_task_id)
  const progress = current ? taskProgress(current) : null
  const failing = !!status.stall || (status.run_state === 'paused' && !!status.pause_reason && status.pause_reason !== 'user')
  const [text, variant, pulse]: [string, StatusPillVariant, boolean] =
    status.stall ? [t('widget.stalled'), 'red', true]
    : status.run_state === 'paused' ? [failing ? t('chip.pausedError') : t('chip.paused'), failing ? 'red' : 'amber', false]
    : status.run_state === 'pausing' ? [t('chip.pausing'), 'amber', true]
    : status.run_state === 'stopping' ? [t('chip.stopping'), 'amber', true]
    : [status.activity ? activityLabel(status.activity) : t('chip.running'), 'green', true]

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between gap-2">
        <span className="truncate text-sm text-slate-200">{current ? taskName(current) : t('chip.label')}</span>
        <StatusPill status={text} variant={variant} pulse={pulse} />
      </div>
      {progress && progress.total > 0 && (
        <>
          <ProgressBar value={progress.done} max={progress.total} label={t('widget.frames', { done: progress.done, total: progress.total })} />
          <div className="flex justify-between font-mono text-xs text-slate-500">
            <span>{t('widget.frames', { done: progress.done, total: progress.total })}</span>
            <span>{fmtSeconds(progress.doneS)} / {fmtSeconds(progress.totalS)}</span>
          </div>
        </>
      )}
      <div className="flex justify-between font-mono text-xs text-slate-500">
        <span>{t('widget.tasks', { done: status.tasks_done, total: status.tasks_total })}</span>
        {status.eta_s != null && <span>{t('widget.eta', { time: fmtSeconds(status.eta_s) })}</span>}
      </div>
    </div>
  )
}
