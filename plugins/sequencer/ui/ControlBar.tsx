// Run state, current activity, progress, and the run controls (driven by run_state only).
import { useEffect, useState } from 'react'
import { Pause, Play, SkipForward, Square } from 'lucide-react'
import { Button } from '@/components/ui/button'
import type {
  SequencerBoundary,
  SequencerPreflightIssue,
  SequencerQueueEntry,
  SequencerStatus,
} from '@/api/types'
import { ACTIVITY_LABEL, fmtSeconds, taskName, taskProgress } from './format'
import { SplitButton, type MenuItem } from './Menu'

const STATE_STYLE: Record<SequencerStatus['run_state'], string> = {
  idle:     'bg-slate-600/30 text-slate-300',
  starting: 'bg-amber-500/20 text-amber-300',
  running:  'bg-emerald-500/20 text-emerald-300',
  pausing:  'bg-amber-500/20 text-amber-300 animate-pulse',
  paused:   'bg-amber-500/20 text-amber-300',
  stopping: 'bg-amber-500/20 text-amber-300 animate-pulse',
}

const REQUEST_LABEL: Record<string, string> = {
  'pause@frame': 'Pausing after this frame…',
  'pause@task': 'Pausing after this task…',
  'stop@frame': 'Stopping after this frame…',
  'stop@task': 'Stopping after this task…',
  'skip@frame': 'Skipping to the next task after this frame…',
  'switch@frame': 'Switching task after this frame…',
  'switch@task': 'Switching task after this one…',
}

function boundaryItems(verb: string, act: (w: SequencerBoundary) => void, withTask = true): MenuItem[] {
  return [
    { label: `${verb} after this frame`, onSelect: () => act('frame') },
    ...(withTask ? [{ label: `${verb} after this task`, onSelect: () => act('task') }] : []),
    { label: `${verb} now`, hint: 'Aborts the exposure in progress (frame discarded)', onSelect: () => act('now') },
  ]
}

function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!active) return
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
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
  const rs = status.run_state
  const current = entries.find((e) => e.task.id === status.current_task_id) ?? null
  const now = useNow(status.exposure_started_at != null)
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
        <span className={`text-xs font-medium uppercase tracking-wide px-2 py-0.5 rounded ${STATE_STYLE[rs]}`}>{rs}</span>
        <span className="text-sm text-slate-200 truncate">
          {status.message ?? (status.activity ? ACTIVITY_LABEL[status.activity] : rs === 'idle' ? '' : '…')}
        </span>
        <span className="ml-auto text-xs text-slate-500">
          {status.tasks_done}/{status.tasks_total} tasks done
          {status.eta_s ? ` · ${fmtSeconds(status.eta_s)} of exposure left` : ''}
        </span>
      </div>

      {current && p && (
        <div className="flex flex-col gap-1.5">
          <div className="flex items-center gap-2 text-xs">
            <span className="text-slate-400 w-20 shrink-0">Task</span>
            <Bar value={p.total ? p.done / p.total : 0} />
            <span className="text-slate-300 w-48 shrink-0 truncate">{taskName(current)} · {p.done}/{p.total}</span>
          </div>
          {exposure && (
            <div className="flex items-center gap-2 text-xs">
              <span className="text-slate-400 w-20 shrink-0">Exposure</span>
              <Bar value={exposure.elapsed / exposure.total} tone="sky" />
              <span className="text-slate-300 w-48 shrink-0 font-mono">
                {Math.round(exposure.elapsed)} / {exposure.total} s
              </span>
            </div>
          )}
        </div>
      )}

      {status.pending_request && REQUEST_LABEL[status.pending_request] && (
        <div className="flex items-center gap-2 text-xs text-amber-300 bg-amber-500/10 rounded px-2 py-1">
          {REQUEST_LABEL[status.pending_request]}
          {status.pending_request.startsWith('pause') && (
            <button className="underline ml-auto" onClick={() => onPause('now')}>Pause now</button>
          )}
          {status.pending_request.startsWith('stop') && (
            <button className="underline ml-auto" onClick={() => onStop('now')}>Stop now</button>
          )}
        </div>
      )}

      {errorPause && (
        <div className="text-xs text-rose-200 bg-rose-500/15 border border-rose-500/30 rounded px-3 py-2">
          <p className="font-medium mb-1">Paused on an error</p>
          <p className="text-rose-300/90">{status.pause_reason}</p>
          <p className="text-rose-300/60 mt-1">Resume retries the failed step; Skip moves on to the next task.</p>
        </div>
      )}

      {rs === 'idle' && status.last_run_outcome && (
        <p className={`text-xs ${status.last_run_outcome === 'failed' ? 'text-status-error' : 'text-slate-500'}`}>
          Last run {status.last_run_outcome}{status.last_error ? `: ${status.last_error}` : ''}
        </p>
      )}
      {rs === 'idle' && errors.length > 0 && (
        <p className="text-xs text-status-error">
          {errors.length} problem{errors.length > 1 ? 's' : ''} to fix before starting (see the tasks below).
        </p>
      )}

      <div className="flex items-center gap-2 flex-wrap">
        {rs === 'idle' && (
          <Button size="sm" onClick={onStart} disabled={busy || runnable.length === 0 || errors.length > 0}>
            <Play size={13} className="mr-1" />
            {runnable.some((e) => e.runtime.status === 'interrupted') ? 'Start / resume' : 'Start'}
          </Button>
        )}
        {(rs === 'running' || rs === 'starting') && (
          <SplitButton label="Pause" icon={<Pause size={13} className="mr-1" />}
            onClick={() => onPause('frame')} items={boundaryItems('Pause', onPause)} />
        )}
        {(rs === 'paused' || rs === 'pausing') && (
          <Button size="sm" onClick={onResume} disabled={busy}>
            <Play size={13} className="mr-1" />
            {rs === 'pausing' ? 'Cancel pause' : errorPause ? 'Resume (retry)' : 'Resume'}
          </Button>
        )}
        {rs !== 'idle' && (
          <SplitButton label="Stop" icon={<Square size={13} className="mr-1" />}
            onClick={() => onStop('frame')} items={boundaryItems('Stop', onStop)} />
        )}
        {rs !== 'idle' && current && (
          <SplitButton label="Skip task" icon={<SkipForward size={13} className="mr-1" />}
            onClick={() => onSkip('frame')} items={boundaryItems('Skip', onSkip, false)} />
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
