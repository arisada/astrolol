// Small display helpers shared by the sequencer components.
import i18n from '@/i18n'
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
  const f = g.filter_name ?? (g.frame_type === 'light' ? '' : i18n.t(`frameType.${g.frame_type}`, { ns: 'common', defaultValue: g.frame_type }))
  return `${f ? `${f} ` : ''}${g.count}×${g.duration}s`
}

/** Frames and seconds of a lane (the primary by default): done / total. */
export function taskProgress(entry: SequencerQueueEntry, laneIndex = 0) {
  const lane = entry.task.lanes[laneIndex]
  const lrt = entry.runtime.lanes[laneIndex]
  let done = 0, total = 0, doneS = 0, totalS = 0
  lane?.groups.forEach((g, i) => {
    const d = Math.min(lrt?.groups[i]?.frames_done ?? 0, g.count)
    done += d; total += g.count
    doneS += d * g.duration; totalS += g.count * g.duration
  })
  return { done, total, doneS, totalS }
}

export const STATUS_STYLE: Record<SequencerTaskStatus, string> = {
  pending:     'text-slate-400',
  running:     'text-accent',
  interrupted: 'text-amber-300',
  completed:   'text-emerald-300',
  failed:      'text-rose-300',
  skipped:     'text-slate-500',
}

/** Translated name of a sequencer activity (the backend sends the key). */
export function activityLabel(a: SequencerActivity): string {
  return i18n.t(`activity.${a}`, { ns: 'sequencer', defaultValue: a })
}
