// One queue entry: name, status, progress, per-group bars, issues, and its actions menu.
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { AlertTriangle, ChevronDown, ChevronRight, GripVertical } from 'lucide-react'
import type { SequencerPreflightIssue, SequencerQueueEntry, SequencerRunState } from '@/api/types'
import { activityLabel, fmtSeconds, groupLabel, STATUS_STYLE, taskName, taskProgress } from './format'
import { MoreMenu, type MenuItem } from './Menu'

export interface TaskActions {
  edit: () => void
  duplicate: () => void
  download: () => void
  startFrom: () => void
  switchTo: () => void
  resetProgress: () => void
  skip: () => void
  unskip: () => void
  remove: () => void
}

function ProgressBar({ value, className = '' }: { value: number; className?: string }) {
  return (
    <div className={`h-1.5 rounded-full bg-surface-border overflow-hidden ${className}`}>
      <div className="h-full bg-accent transition-all" style={{ width: `${Math.min(100, Math.max(0, value * 100))}%` }} />
    </div>
  )
}

export function TaskCard({
  entry, isCurrent, runState, issues, actions, dragProps,
}: {
  entry: SequencerQueueEntry
  isCurrent: boolean
  runState: SequencerRunState
  issues: SequencerPreflightIssue[]
  actions: TaskActions
  dragProps: React.HTMLAttributes<HTMLDivElement> & { draggable: boolean }
}) {
  const { t } = useTranslation('sequencer')
  const [expanded, setExpanded] = useState(isCurrent)
  const { task, runtime } = entry
  const status = runtime.status
  const running = status === 'running'
  const idle = runState === 'idle'
  const runnable = status === 'pending' || status === 'interrupted'
  const switchable = runnable || status === 'failed' || status === 'skipped'
  const p = taskProgress(entry)
  const lane = task.lanes[0]
  const lastInterruption = runtime.interruptions[runtime.interruptions.length - 1]
  const hasErrors = issues.some((i) => i.severity === 'error')

  const menu: MenuItem[] = [
    { label: t('card.edit'), onSelect: actions.edit, disabled: running },
    { label: t('card.duplicate'), onSelect: actions.duplicate },
    { label: t('card.download'), onSelect: actions.download, hint: t('card.downloadHint') },
    idle
      ? { label: t('card.startFrom'), onSelect: actions.startFrom, disabled: !runnable,
          hint: t('card.startFromHint') }
      : { label: t('card.switchTo'), onSelect: actions.switchTo, disabled: !switchable || isCurrent,
          hint: t('card.switchHint') },
    status === 'skipped'
      ? { label: t('card.unskip'), onSelect: actions.unskip }
      : { label: running ? t('card.skipAfter') : t('card.skip'), onSelect: actions.skip,
          disabled: status === 'completed' },
    { label: t('card.reset'), onSelect: actions.resetProgress, disabled: running || p.done === 0 },
    { label: t('card.delete'), onSelect: actions.remove, disabled: running, danger: true },
  ]

  return (
    <div
      {...dragProps}
      className={`rounded border px-3 py-2 transition-colors
        ${isCurrent ? 'border-accent/60 bg-surface-overlay' : 'border-surface-border bg-surface-raised'}
        ${status === 'completed' || status === 'skipped' ? 'opacity-70' : ''}`}
    >
      <div className="flex items-center gap-2">
        <GripVertical size={14} className={`shrink-0 ${dragProps.draggable ? 'text-slate-600 cursor-grab' : 'text-transparent'}`} />
        <button type="button" onClick={() => setExpanded((e) => !e)} className="text-slate-500 hover:text-slate-300">
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </button>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-sm font-medium text-slate-100 truncate">{taskName(entry)}</span>
            {task.name && task.name !== task.target.name && (
              <span className="text-xs text-slate-500 truncate">{task.target.name}</span>
            )}
            {hasErrors && <AlertTriangle size={12} className="text-status-error shrink-0" />}
          </div>
          <div className="flex items-center gap-2 mt-1">
            <ProgressBar value={p.total ? p.done / p.total : 0} className="w-32 shrink-0" />
            <span className="text-xs text-slate-500 truncate">
              {t('card.progress', { done: p.done, total: p.total, doneTime: fmtSeconds(p.doneS), totalTime: fmtSeconds(p.totalS) })}
              {' · '}{lane.groups.map(groupLabel).join(', ')}
            </span>
          </div>
        </div>
        <span className={`text-xs px-2 py-0.5 rounded-full shrink-0 ${STATUS_STYLE[status]}`}>{t(`taskStatus.${status}`)}</span>
        <MoreMenu items={menu} />
      </div>

      {runtime.stall && (
        <p className="text-xs text-amber-300 mt-1 ml-10">
          {t('card.stalled', { kind: t(`control.stall.${runtime.stall.kind}`, { defaultValue: runtime.stall.kind }), count: runtime.stall.attempts })}
          {runtime.stall.last_error ? ` — ${runtime.stall.last_error}` : ''}
        </p>
      )}
      {runtime.last_error && status !== 'completed' && (
        <p className="text-xs text-status-error mt-1 ml-10">{runtime.last_error}</p>
      )}
      {status === 'interrupted' && lastInterruption && (
        <p className="text-xs text-amber-300/80 mt-1 ml-10">
          {t('card.interruption', { kind: lastInterruption.kind, actor: lastInterruption.actor })}
          {lastInterruption.reason ? ` — ${lastInterruption.reason}` : ''}
        </p>
      )}
      {issues.length > 0 && (
        <ul className="mt-1 ml-10 flex flex-col gap-0.5">
          {issues.map((i, k) => (
            <li key={k} className={`text-xs ${i.severity === 'error' ? 'text-status-error' : 'text-yellow-400/90'}`}>
              {i.message.replace(`${taskName(entry)}: `, '')}
            </li>
          ))}
        </ul>
      )}

      {expanded && (
        <div className="mt-2 ml-10 flex flex-col gap-1.5">
          {task.lanes.map((ln, li) => {
            const lr = runtime.lanes[li]
            return (
              <div key={ln.id ?? li} className="flex flex-col gap-1">
                {task.lanes.length > 1 && (
                  <span className="text-[11px] text-slate-400">
                    {li === 0 ? t('card.primary') : t('card.camera')} · {ln.camera_id ?? t('card.mainCamera')}
                    {isCurrent && lr?.activity ? ` · ${activityLabel(lr.activity).toLowerCase()}` : ''}
                  </span>
                )}
                {ln.groups.map((g, i) => {
                  const done = Math.min(lr?.groups[i]?.frames_done ?? 0, g.count)
                  const active = isCurrent && lr?.current_group === i
                  return (
                    <div key={i} className="flex items-center gap-2 text-xs">
                      <span className={`w-28 truncate ${active ? 'text-accent' : 'text-slate-400'}`}>{groupLabel(g)}</span>
                      <ProgressBar value={done / g.count} className="w-40" />
                      <span className="text-slate-500 font-mono">{done}/{g.count}</span>
                    </div>
                  )
                })}
              </div>
            )
          })}
          <p className="text-[11px] text-slate-500">
            {[
              task.target.kind === 'current' ? t('card.plan.noSlew') : [task.slew && t('card.plan.slew'), task.center && t('card.plan.center')].filter(Boolean).join(' + '),
              task.start_guiding && t('card.plan.guide'),
              task.autofocus_at_start && t('card.plan.autofocus'),
              lane.autofocus_on_filter_change && t('card.plan.refocus'),
              task.dither_every ? t('card.plan.ditherEvery', { n: task.dither_every }) : t('card.plan.noDither'),
              lane.order === 'round_robin' && t('card.plan.roundRobin', { n: lane.round_robin_batch }),
              t('card.plan.onError', { action: task.on_error }),
            ].filter(Boolean).join(' · ')}
          </p>
        </div>
      )}
    </div>
  )
}
