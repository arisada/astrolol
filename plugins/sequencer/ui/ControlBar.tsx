// Run state, current activity, progress, and the run controls (driven by run_state only).
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'
import { Pause, Play, SkipForward, Square } from 'lucide-react'
import { Button } from '@/components/ui/button'
import type {
  SequencerBoundary,
  SequencerPreflightIssue,
  SequencerQueueEntry,
  SequencerStatus,
} from '@/api/types'
import { activityLabel, fmtSeconds, taskName, taskProgress } from './format'
import { SplitButton, type MenuItem } from './Menu'

const STATE_STYLE: Record<SequencerStatus['run_state'], string> = {
  idle:     'bg-slate-600/30 text-slate-300',
  starting: 'bg-amber-500/20 text-amber-300',
  running:  'bg-emerald-500/20 text-emerald-300',
  pausing:  'bg-amber-500/20 text-amber-300 animate-pulse',
  paused:   'bg-amber-500/20 text-amber-300',
  stopping: 'bg-amber-500/20 text-amber-300 animate-pulse',
}

function boundaryItems(
  verb: 'pause' | 'stop' | 'skip', t: TFunction, act: (w: SequencerBoundary) => void, withTask = true,
): MenuItem[] {
  return [
    { label: t(`control.boundary.${verb}.frame`), onSelect: () => act('frame') },
    ...(withTask ? [{ label: t(`control.boundary.${verb}.task`), onSelect: () => act('task') }] : []),
    { label: t(`control.boundary.${verb}.now`), hint: t('control.boundary.abortHint'), onSelect: () => act('now') },
  ]
}

function sinceLabel(t: TFunction, iso: string, now: number, future = false): string {
  const s = Math.max(0, Math.round(((future ? Date.parse(iso) - now : now - Date.parse(iso))) / 1000))
  const text = s < 90 ? t('control.since.seconds', { n: s }) : t('control.since.minutes', { n: Math.round(s / 60) })
  return t(future ? 'control.since.in' : 'control.since.for', { text })
}

function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!active) return
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [active])
  return now
}

export function ControlBar({
  status, entries, preflightIssues, busy, onStart, onPause, onResume, onStop, onSkip,
}: {
  status: SequencerStatus
  entries: SequencerQueueEntry[]
  preflightIssues: SequencerPreflightIssue[]
  busy: boolean
  onStart: () => void
  onPause: (w: SequencerBoundary) => void
  onResume: () => void
  onStop: (w: SequencerBoundary) => void
  onSkip: (w: SequencerBoundary) => void
}) {
  const { t } = useTranslation('sequencer')
  const rs = status.run_state
  const current = entries.find((e) => e.task.id === status.current_task_id) ?? null
  const now = useNow(status.exposure_started_at != null || status.stall != null)
  const runnable = entries.filter((e) => e.runtime.status === 'pending' || e.runtime.status === 'interrupted')
  const errors = preflightIssues.filter((i) => i.severity === 'error')
  const errorPause = rs === 'paused' && status.pause_reason && status.pause_reason !== 'user'

  let exposure: { elapsed: number; total: number } | null = null
  if (status.exposure_started_at && status.exposure_duration) {
    const elapsed = Math.max(0, (now - Date.parse(status.exposure_started_at)) / 1000)
    exposure = { elapsed: Math.min(elapsed, status.exposure_duration), total: status.exposure_duration }
  }
  const p = current ? taskProgress(current) : null

  return (
    <section className="rounded-lg border border-surface-border bg-surface-raised p-4 flex flex-col gap-3">
      <div className="flex items-center gap-3 flex-wrap">
        <span className={`font-medium label-caps px-2 py-0.5 rounded ${STATE_STYLE[rs]}`}>{t(`runState.${rs}`)}</span>
        <span className="text-sm text-slate-200 truncate">
          {status.message ?? (status.activity ? activityLabel(status.activity) : rs === 'idle' ? '' : '…')}
        </span>
        <span className="ml-auto text-xs text-slate-500">
          {t('control.tasksDone', { done: status.tasks_done, total: status.tasks_total })}
          {status.eta_s ? t('control.etaLeft', { time: fmtSeconds(status.eta_s) }) : ''}
        </span>
      </div>

      {current && p && (
        <div className="flex flex-col gap-1.5">
          <div className="flex items-center gap-2 text-xs">
            <span className="text-slate-400 w-20 shrink-0">{t('control.task')}</span>
            <Bar value={p.total ? p.done / p.total : 0} />
            <span className="text-slate-300 w-48 shrink-0 truncate">{taskName(current)} · {p.done}/{p.total}</span>
          </div>
          {current.task.lanes.slice(1).map((ln, k) => {
            const i = k + 1
            const lp = taskProgress(current, i)
            const activity = status.lanes[i]?.activity
            return (
              <div key={ln.id ?? i} className="flex items-center gap-2 text-xs">
                <span className="text-slate-400 w-20 shrink-0 truncate" title={ln.camera_id ?? ''}>{ln.camera_id ?? t('control.cameraN', { n: i + 1 })}</span>
                <Bar value={lp.total ? lp.done / lp.total : 0} />
                <span className="text-slate-300 w-48 shrink-0 truncate">
                  {lp.done}/{lp.total} · {activity ? activityLabel(activity).toLowerCase() : t('control.idle')}
                </span>
              </div>
            )
          })}
          {exposure && (
            <div className="flex items-center gap-2 text-xs">
              <span className="text-slate-400 w-20 shrink-0">{t('control.exposure')}</span>
              <Bar value={exposure.elapsed / exposure.total} tone="sky" />
              <span className="text-slate-300 w-48 shrink-0 font-mono">
                {Math.round(exposure.elapsed)} / {exposure.total} s
              </span>
            </div>
          )}
        </div>
      )}

      {status.pending_request && t(`control.request.${status.pending_request}`, { defaultValue: '' }) && (
        <div className="flex items-center gap-2 text-xs text-amber-300 bg-amber-500/10 rounded px-2 py-1">
          {t(`control.request.${status.pending_request}`)}
          {status.pending_request.startsWith('pause') && (
            <button className="underline ml-auto" onClick={() => onPause('now')}>{t('control.pauseNow')}</button>
          )}
          {status.pending_request.startsWith('stop') && (
            <button className="underline ml-auto" onClick={() => onStop('now')}>{t('control.stopNow')}</button>
          )}
        </div>
      )}

      {status.stall && (
        <div className="text-xs text-amber-200 bg-amber-500/10 border border-amber-500/30 rounded px-3 py-2">
          <p className="font-medium">
            {t('control.stall.title', { what: t(`control.stall.${status.stall.kind}`), since: sinceLabel(t, status.stall.since, now) })}
            {status.stall.attempts > 0 && t('control.stall.attempts', { count: status.stall.attempts })}
          </p>
          {status.stall.last_error && <p className="text-amber-300/80">{status.stall.last_error}</p>}
          <p className="text-amber-300/60 mt-1">
            {t('control.stall.retrying', { next: status.stall.next_attempt_at ? t('control.stall.next', { when: sinceLabel(t, status.stall.next_attempt_at, now, true) }) : '' })}
            {status.stall.kind === 'autofocus' ? t('control.stall.keepsImaging') : t('control.stall.waits')}
          </p>
        </div>
      )}

      {errorPause && (
        <div className="text-xs text-rose-200 bg-rose-500/15 border border-rose-500/30 rounded px-3 py-2">
          <p className="font-medium mb-1">{t('control.errorPause')}</p>
          <p className="text-rose-300/90">{status.pause_reason}</p>
          <p className="text-rose-300/60 mt-1">{t('control.errorHint')}</p>
        </div>
      )}

      {rs === 'idle' && status.last_run_outcome && (
        <p className={`text-xs ${status.last_run_outcome === 'failed' ? 'text-status-error' : 'text-slate-500'}`}>
          {t('control.lastRun', { outcome: t(`taskStatus.${status.last_run_outcome}`, { defaultValue: status.last_run_outcome }), error: status.last_error ? `: ${status.last_error}` : '' })}
        </p>
      )}
      {rs === 'idle' && errors.length > 0 && (
        <p className="text-xs text-status-error">
          {t('control.problems', { count: errors.length })}
        </p>
      )}

      <div className="flex items-center gap-2 flex-wrap">
        {rs === 'idle' && (
          <Button size="sm" onClick={onStart} disabled={busy || runnable.length === 0 || errors.length > 0}>
            <Play size={13} className="mr-1" />
            {runnable.some((e) => e.runtime.status === 'interrupted') ? t('control.startResume') : t('control.start')}
          </Button>
        )}
        {(rs === 'running' || rs === 'starting') && (
          <SplitButton label={t('control.pause')} icon={<Pause size={13} className="mr-1" />}
            onClick={() => onPause('frame')} items={boundaryItems('pause', t, onPause)} />
        )}
        {(rs === 'paused' || rs === 'pausing') && (
          <Button size="sm" onClick={onResume} disabled={busy}>
            <Play size={13} className="mr-1" />
            {rs === 'pausing' ? t('control.cancelPause') : errorPause ? t('control.resumeRetry') : t('control.resume')}
          </Button>
        )}
        {rs !== 'idle' && (
          <SplitButton label={t('control.stop')} icon={<Square size={13} className="mr-1" />}
            onClick={() => onStop('frame')} items={boundaryItems('stop', t, onStop)} />
        )}
        {rs !== 'idle' && current && (
          <SplitButton label={t('control.skipTask')} icon={<SkipForward size={13} className="mr-1" />}
            onClick={() => onSkip('frame')} items={boundaryItems('skip', t, onSkip, false)} />
        )}
      </div>
    </section>
  )
}

function Bar({ value, tone = 'accent' }: { value: number; tone?: 'accent' | 'sky' }) {
  return (
    <div className="flex-1 h-1.5 rounded-full bg-surface-border overflow-hidden">
      <div className={`h-full transition-all ${tone === 'sky' ? 'bg-sky-400' : 'bg-accent'}`}
        style={{ width: `${Math.min(100, Math.max(0, value * 100))}%` }} />
    </div>
  )
}
