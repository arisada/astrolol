// Small display helpers shared by the sequencer components.
import type {
  SequencerActivity,
  SequencerExposureGroup,
  SequencerQueueEntry,
  SequencerTaskStatus,
} from '@/api/types'

export function fmtSeconds(s: number): string {
  if (s < 60) return `${Math.round(s)} s`
  const h = Math.floor(s / 3600)
  const m = Math.round((s % 3600) / 60)
  if (h === 0) return `${m} min`
  return m === 0 ? `${h} h` : `${h} h ${m.toString().padStart(2, '0')}`
}

export function taskName(entry: SequencerQueueEntry): string {
  return entry.task.name || entry.task.target.name
}

export function groupLabel(g: SequencerExposureGroup): string {
  const f = g.filter_name ?? (g.frame_type === 'light' ? '' : g.frame_type)
  return `${f ? `${f} ` : ''}${g.count}×${g.duration}s`
}

/** Frames and seconds of the primary lane: done / total. */
export function taskProgress(entry: SequencerQueueEntry) {
  const lane = entry.task.lanes[0]
  const lrt = entry.runtime.lanes[0]
  let done = 0, total = 0, doneS = 0, totalS = 0
  lane.groups.forEach((g, i) => {
    const d = Math.min(lrt?.groups[i]?.frames_done ?? 0, g.count)
    done += d; total += g.count
    doneS += d * g.duration; totalS += g.count * g.duration
  })
  return { done, total, doneS, totalS }
}

export const STATUS_STYLE: Record<SequencerTaskStatus, string> = {
  pending:     'text-slate-400 bg-slate-500/15',
  running:     'text-accent bg-accent/20',
  interrupted: 'text-amber-300 bg-amber-500/15',
  completed:   'text-emerald-300 bg-emerald-500/15',
  failed:      'text-rose-300 bg-rose-500/15',
  skipped:     'text-slate-500 bg-slate-600/20',
}

export const ACTIVITY_LABEL: Record<SequencerActivity, string> = {
  unparking: 'Unparking',
  slewing: 'Slewing',
  centering: 'Centering',
  starting_guiding: 'Starting guiding',
  focusing: 'Focusing',
  changing_filter: 'Changing filter',
  exposing: 'Exposing',
  dithering: 'Dithering',
  waiting_for_primary: 'Waiting for primary',
  waiting_for_guiding: 'Waiting for guiding',
  meridian_flip: 'Meridian flip',
  parking: 'Parking',
  waiting: 'Waiting',
}
