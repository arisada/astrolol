// Session journal: past runs, where the time went, what was captured, what happened.
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'
import { Download } from 'lucide-react'
import type { SequencerSessionSummary } from '@/api/types'
import { getSessionRecords, getSessions, sessionExportUrl, type JournalRecord } from './api'
import { activityLabel, fmtSeconds } from './format'

// Activities folded into six groups (categorical colours cat-1…cat-5 of the active palette;
// "other" is neutral).
const GROUPS = [
  { key: 'imaging', color: 'rgb(var(--c-cat-1))', activities: ['exposing'] },
  {
    key: 'setup', color: 'rgb(var(--c-cat-2))',
    activities: ['slewing', 'centering', 'unparking', 'parking', 'meridian_flip', 'changing_filter'],
  },
  {
    key: 'guiding', color: 'rgb(var(--c-cat-3))',
    activities: ['starting_guiding', 'dithering', 'waiting_for_guiding'],
  },
  { key: 'focusing', color: 'rgb(var(--c-cat-4))', activities: ['focusing'] },
  { key: 'paused', color: 'rgb(var(--c-cat-5))', activities: ['paused'] },
  { key: 'other', color: 'rgb(var(--c-cat-6))', activities: [] as string[] },
] as const

function groupOf(activity: string) {
  return GROUPS.find((g) => (g.activities as readonly string[]).includes(activity)) ?? GROUPS[GROUPS.length - 1]
}

const localTime = (iso: string | null, lng: string) => (iso ? new Date(iso).toLocaleString(lng) : '—')
const clock = (iso: string, lng: string) => new Date(iso).toLocaleTimeString(lng, { hour: '2-digit', minute: '2-digit' })

export function JournalView() {
  const { t, i18n } = useTranslation('sequencer')
  const lng = i18n.language
  const [sessions, setSessions] = useState<SequencerSessionSummary[] | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getSessions()
      .then((s) => { setSessions(s); setSelected((cur) => cur ?? s[0]?.session_id ?? null) })
      .catch((e: Error) => setError(e.message))
  }, [])

  if (error) return <p className="text-sm text-status-error">{error}</p>
  if (!sessions) return <p className="text-sm text-slate-500">{t('loading')}</p>
  if (sessions.length === 0) {
    return <p className="text-sm text-slate-500">{t('journal.none')}</p>
  }
  const summary = sessions.find((s) => s.session_id === selected) ?? null

  return (
    <div className="flex flex-col gap-4">
      <table className="tbl w-full text-xs">
        <thead className="text-slate-500 text-left">
          <tr>
            <th className="font-normal py-1">{t('journal.cols.started')}</th>
            <th className="font-normal">{t('journal.cols.duration')}</th>
            <th className="font-normal">{t('journal.cols.outcome')}</th>
            <th className="font-normal">{t('journal.cols.targets')}</th>
            <th className="font-normal text-right">{t('journal.cols.frames')}</th>
            <th className="font-normal text-right">{t('journal.cols.integration')}</th>
          </tr>
        </thead>
        <tbody>
          {sessions.map((s) => (
            <tr
              key={s.session_id}
              onClick={() => setSelected(s.session_id)}
              className={`cursor-pointer border-t border-surface-border hover:bg-surface-overlay
                ${s.session_id === selected ? 'bg-surface-overlay text-slate-100' : 'text-slate-300'}`}
            >
              <td className="py-1.5">{localTime(s.started_at, lng)}</td>
              <td>{fmtSeconds(s.duration_s)}</td>
              <td>{s.outcome ?? (s.finished_at ? '—' : t('journal.notFinished'))}</td>
              <td className="truncate max-w-[16rem]">{s.tasks.join(', ') || '—'}</td>
              <td className="text-right font-mono">{s.frames_saved}</td>
              <td className="text-right font-mono">{fmtSeconds(s.integration_s)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {summary && <SessionDetail key={summary.session_id} summary={summary} />}
    </div>
  )
}

function SessionDetail({ summary }: { summary: SequencerSessionSummary }) {
  const { t, i18n } = useTranslation('sequencer')
  const lng = i18n.language
  const [records, setRecords] = useState<JournalRecord[] | null>(null)
  useEffect(() => {
    getSessionRecords(summary.session_id).then(setRecords).catch(() => setRecords([]))
  }, [summary.session_id])

  const grouped = useMemo(() => {
    const totals = new Map<string, { seconds: number; parts: string[] }>()
    for (const row of summary.time) {
      if (row.activity === 'idle') continue
      const g = groupOf(row.activity)
      const cur = totals.get(g.key) ?? { seconds: 0, parts: [] }
      cur.seconds += row.seconds
      cur.parts.push(`${activityLabel(row.activity as never).toLowerCase()} ${fmtSeconds(row.seconds)}`)
      totals.set(g.key, cur)
    }
    return GROUPS.filter((g) => (totals.get(g.key)?.seconds ?? 0) >= 1).map((g) => ({ ...g, ...totals.get(g.key)! }))
  }, [summary.time])
  const total = grouped.reduce((s, g) => s + g.seconds, 0) || 1

  const frames = (records ?? []).filter((r) => r.type === 'sequencer.frame_saved')
  const notable = (records ?? []).filter((r) => [
    'sequencer.interruption', 'sequencer.task_stalled', 'sequencer.task_unstalled',
    'sequencer.step_failed', 'sequencer.task_finished', 'sequencer.resumed', 'guiding.state_changed',
  ].includes(r.type) || (r.type === 'sequencer.step_finished' && NOTABLE_STEPS.has(String(r.step))))

  return (
    <div className="flex flex-col gap-5 border-t border-surface-border pt-4">
      <div className="flex items-start gap-4 flex-wrap">
        <div className="flex-1 min-w-0">
          <h2 className="text-sm font-semibold text-slate-100">
            {localTime(summary.started_at, lng)} → {summary.finished_at ? localTime(summary.finished_at, lng) : t('journal.notFinished')}
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            {summary.outcome ?? t('journal.noOutcome')}{summary.error ? ` — ${summary.error}` : ''}
            {summary.actor ? t('journal.startedBy', { actor: summary.actor }) : ''}
          </p>
        </div>
        <div className="flex gap-2">
          {(['md', 'csv'] as const).map((f) => (
            <a key={f} href={sessionExportUrl(summary.session_id, f)} download
              className="inline-flex items-center gap-1 px-2 py-1 text-xs rounded border border-surface-border text-slate-300 hover:bg-surface-overlay">
              <Download size={12} /> {f === 'md' ? t('journal.reportMd') : t('journal.framesCsv')}
            </a>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <Stat label={t('journal.stats.integration')} value={fmtSeconds(summary.integration_s)} />
        <Stat label={t('journal.stats.saved')} value={`${summary.frames_saved}`}
          note={summary.frames_uncounted ? t('journal.stats.notCounted', { count: summary.frames_uncounted }) : undefined} />
        <Stat label={t('journal.stats.interruptions')} value={`${summary.interruptions} / ${summary.stalls}`} />
        <Stat label={t('journal.stats.failed')} value={`${summary.step_failures}`}
          note={summary.frames_discarded ? t('journal.stats.discarded', { count: summary.frames_discarded }) : undefined} />
      </div>

      {grouped.length > 0 && (
        <section>
          <h3 className="font-medium text-slate-500 label-caps mb-2">{t('journal.where')}</h3>
          <div className="flex h-4 w-full gap-[2px] rounded overflow-hidden" role="img"
            aria-label={grouped.map((g) => `${t(`journal.groups.${g.key}`)} ${Math.round((100 * g.seconds) / total)}%`).join(', ')}>
            {grouped.map((g) => (
              <div key={g.key} style={{ width: `${(100 * g.seconds) / total}%`, background: g.color }}
                title={`${t(`journal.groups.${g.key}`)}: ${fmtSeconds(g.seconds)} (${Math.round((100 * g.seconds) / total)} %)\n${g.parts.join('\n')}`} />
            ))}
          </div>
          <ul className="mt-2 grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-1 text-xs">
            {grouped.map((g) => (
              <li key={g.key} className="flex items-center gap-2 text-slate-300" title={g.parts.join('\n')}>
                <span className="w-2.5 h-2.5 rounded-sm shrink-0" style={{ background: g.color }} />
                <span>{t(`journal.groups.${g.key}`)}</span>
                <span className="ml-auto font-mono text-slate-400">
                  {fmtSeconds(g.seconds)} · {Math.round((100 * g.seconds) / total)} %
                </span>
              </li>
            ))}
          </ul>
          {records && <Timeline records={records} summary={summary} />}
        </section>
      )}

      {summary.integration.length > 0 && (
        <section>
          <h3 className="font-medium text-slate-500 label-caps mb-2">{t('journal.captured')}</h3>
          <table className="tbl w-full text-xs">
            <thead className="text-slate-500 text-left">
              <tr>
                <th className="font-normal py-1">{t('journal.capturedCols.target')}</th><th className="font-normal">{t('journal.capturedCols.camera')}</th>
                <th className="font-normal">{t('journal.capturedCols.filter')}</th>
                <th className="font-normal text-right">{t('journal.capturedCols.frames')}</th><th className="font-normal text-right">{t('journal.capturedCols.time')}</th>
                <th className="font-normal text-right">{t('journal.capturedCols.uncounted')}</th>
              </tr>
            </thead>
            <tbody>
              {summary.integration.map((row) => (
                <tr key={`${row.object_name}/${row.camera_id}/${row.filter_name}`} className="border-t border-surface-border text-slate-300">
                  <td className="py-1">{row.object_name}</td><td>{row.camera_id ?? '—'}</td>
                  <td>{row.filter_name ?? '—'}</td>
                  <td className="text-right font-mono">{row.frames}</td>
                  <td className="text-right font-mono">{fmtSeconds(row.seconds)}</td>
                  <td className="text-right font-mono">{row.uncounted || ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {notable.length > 0 && (
        <section>
          <h3 className="font-medium text-slate-500 label-caps mb-2">{t('journal.events')}</h3>
          <ul className="text-xs flex flex-col gap-1">
            {notable.map((r, i) => (
              <li key={i} className="flex gap-3">
                <span className="font-mono text-slate-500 shrink-0">{clock(r.timestamp, lng)}</span>
                <span className="text-slate-300">{describe(t, r)}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {frames.length > 0 && (
        <section>
          <h3 className="font-medium text-slate-500 label-caps mb-2">{t('journal.framesTitle')}</h3>
          <div className="max-h-72 overflow-y-auto">
            <table className="tbl w-full text-xs">
              <thead className="text-slate-500 text-left sticky top-0 bg-surface">
                <tr>
                  <th className="font-normal py-1">{t('journal.frameCols.time')}</th><th className="font-normal">{t('journal.frameCols.target')}</th>
                  <th className="font-normal">{t('journal.frameCols.camera')}</th><th className="font-normal">{t('journal.frameCols.filter')}</th><th className="font-normal text-right">{t('journal.frameCols.exp')}</th>
                  <th className="font-normal text-right">{t('journal.frameCols.rms')}</th><th className="font-normal text-right">{t('journal.frameCols.unguided')}</th>
                  <th className="font-normal text-right">{t('journal.frameCols.alt')}</th><th className="font-normal text-right">{t('journal.frameCols.focus')}</th>
                  <th className="font-normal text-right">{t('journal.frameCols.sensor')}</th>
                </tr>
              </thead>
              <tbody className="font-mono">
                {frames.map((f, i) => (
                  <tr key={i} className={`border-t border-surface-border ${f.counted === false ? 'text-slate-500 line-through' : 'text-slate-300'}`}
                    title={String(f.fits_path ?? '')}>
                    <td className="py-1">{clock(f.timestamp, lng)}</td>
                    <td className="font-sans">{String(f.object_name ?? '')}</td>
                    <td className="font-sans">{String(f.camera_id ?? '—')}</td>
                    <td className="font-sans">{String(f.filter_name ?? '—')}</td>
                    <td className="text-right">{num(f.duration, 0)} s</td>
                    <td className="text-right">{num(f.guide_rms_total, 2, '″')}</td>
                    <td className="text-right">{num(f.unguided_s, 0, ' s')}</td>
                    <td className="text-right">{num(f.altitude, 1, '°')}</td>
                    <td className="text-right">{num(f.focuser_position, 0)}</td>
                    <td className="text-right">{num(f.sensor_temperature, 1, ' °C')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  )
}

function Timeline({ records, summary }: { records: JournalRecord[]; summary: SequencerSessionSummary }) {
  const { t, i18n } = useTranslation('sequencer')
  const lng = i18n.language
  const start = summary.started_at ? Date.parse(summary.started_at) : NaN
  const end = start + summary.duration_s * 1000
  const span = end - start
  const segments = useMemo(() => {
    const marks = records.filter((r) => r.type === 'journal.activity')
    return marks.map((r, i) => {
      const t0 = Date.parse(r.timestamp)
      const t1 = i + 1 < marks.length ? Date.parse(marks[i + 1].timestamp) : end
      const activity = r.run_state === 'paused' ? 'paused' : String(r.activity ?? 'other')
      return { t0, t1, activity, group: groupOf(activity) }
    }).filter((s) => s.t1 > s.t0 && s.activity !== 'idle')
  }, [records, end])
  if (!Number.isFinite(start) || span <= 0 || segments.length === 0) return null
  const pct = (ms: number) => `${(100 * (ms - start)) / span}%`
  return (
    <div className="mt-4">
      <div className="relative h-5 w-full rounded bg-surface-overlay">
        {segments.map((s, i) => (
          <div key={i} className="absolute top-0 h-full border-r-2 border-surface"
            style={{ left: pct(s.t0), width: `${(100 * (s.t1 - s.t0)) / span}%`, background: s.group.color }}
            title={`${new Date(s.t0).toLocaleTimeString(lng)} – ${new Date(s.t1).toLocaleTimeString(lng)}: ${s.activity === 'paused' ? t('journal.groups.paused') : activityLabel(s.activity as never).toLowerCase()}`} />
        ))}
      </div>
      <div className="flex justify-between text-[11px] text-slate-500 mt-1 font-mono">
        <span>{clock(new Date(start).toISOString(), lng)}</span>
        <span>{clock(new Date(end).toISOString(), lng)}</span>
      </div>
    </div>
  )
}

function Stat({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="rounded border border-surface-border bg-surface-raised px-3 py-2">
      <div className="text-[11px] text-slate-500">{label}</div>
      <div className="text-sm text-slate-100 font-mono">{value}</div>
      {note && <div className="text-[11px] text-slate-500">{note}</div>}
    </div>
  )
}

function num(v: unknown, digits: number, unit = ''): string {
  return typeof v === 'number' ? `${v.toFixed(digits)}${unit}` : '—'
}

const NOTABLE_STEPS = new Set(['autofocus', 'center', 'meridian_flip'])

function describe(t: TFunction, r: JournalRecord): string {
  const s = (k: string) => String(r[k] ?? '')
  const details = (r.details ?? {}) as Record<string, unknown>
  const d = (key: string, opts?: Record<string, unknown>) => t(`journal.describe.${key}`, opts)
  switch (r.type) {
    case 'guiding.state_changed':
      return r.guiding ? d('guidingStarted') : d('guidingInterrupted', { reason: s('reason').replace(/_/g, ' ') })
    case 'sequencer.step_finished':
      if (r.step === 'autofocus') return d('autofocus', { reason: String(details.reason ?? ''), position: String(details.position ?? '?') })
      if (r.step === 'center') return d('center', { attempts: String(details.attempts ?? '?'), error: String(details.final_error_arcsec ?? '?') })
      return d('flip', { before: String(details.pier_before ?? '?'), after: String(details.pier_after ?? '?') })
    case 'sequencer.interruption': return d('interruption', { kind: s('kind'), actor: s('actor'), reason: r.reason ? `: ${s('reason')}` : '' })
    case 'sequencer.resumed': return d('resumed', { time: fmtSeconds(Number(r.paused_s)), rerun: r.setup_rerun ? d('setupRerun') : '' })
    case 'sequencer.task_stalled': return d('stalled', { kind: s('kind'), error: s('error') })
    case 'sequencer.task_unstalled': return d('unstalled', { kind: s('kind'), time: fmtSeconds(Number(r.duration_s)), attempts: s('attempts') })
    case 'sequencer.step_failed': return d('stepFailed', { step: s('step'), handling: s('handling'), error: s('error') })
    case 'sequencer.task_finished': return d('taskFinished', { status: s('status'), error: r.error ? `: ${s('error')}` : '' })
    default: return r.type
  }
}
