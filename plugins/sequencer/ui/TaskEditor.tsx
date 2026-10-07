// Drawer to create or edit a task: target, cameras (lanes) with their exposure groups, options.
import { useEffect, useMemo, useState } from 'react'
import { Trans, useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'
import { ArrowDown, ArrowUp, Crown, Plus, Trash2, X } from 'lucide-react'
import { api } from '@/api/client'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { PillGroup } from '@/components/ui/pill-group'
import { ToggleSwitch } from '@/components/ui/toggle-switch'
import { useStore } from '@/store'
import type {
  ConnectedDevice,
  OpticalPath,
  SequencerExposureGroup,
  SequencerLane,
  SequencerLaneEstimate,
  SequencerQueueEntry,
  SequencerTargetRef,
  SequencerTask,
} from '@/api/types'
import { addTask, estimate, updateTask } from './api'
import { fmtSeconds } from './format'
import { TargetPicker } from './TargetPicker'

interface GroupRow {
  filter_name: string   // '' = don't touch the wheel
  duration: string
  count: string
  gain: string          // '' = leave driver gain unchanged
  binning: number
  frame_type: SequencerExposureGroup['frame_type']
}

interface LaneDraft {
  key: string                 // React key (lane id when editing)
  id?: string                 // existing lane id: keeps its progress
  cameraId: string            // '' = main camera
  rows: GroupRow[]
  order: 'sequential' | 'round_robin'
  batch: string
  afFilter: boolean
}

function toRow(g: SequencerExposureGroup): GroupRow {
  return {
    filter_name: g.filter_name ?? '',
    duration: String(g.duration),
    count: String(g.count),
    gain: g.gain == null ? '' : String(g.gain),
    binning: g.binning,
    frame_type: g.frame_type,
  }
}

function parseRow(t: TFunction, r: GroupRow): SequencerExposureGroup | string {
  const duration = Number(r.duration)
  const count = Number(r.count)
  if (!(duration > 0)) return t('editor.errors.duration')
  if (!Number.isInteger(count) || count < 1) return t('editor.errors.count')
  let gain: number | null = null
  if (r.gain.trim() !== '') {
    gain = Number(r.gain)
    if (!Number.isInteger(gain) || gain < 0) return t('editor.errors.gain')
  }
  return { filter_name: r.filter_name || null, duration, count, gain, binning: r.binning, frame_type: r.frame_type }
}

const NEW_ROW: GroupRow = { filter_name: '', duration: '300', count: '10', gain: '', binning: 1, frame_type: 'light' }
let draftCounter = 0
const newKey = () => `draft-${++draftCounter}`

function laneToDraft(lane: SequencerLane): LaneDraft {
  return {
    key: lane.id ?? newKey(),
    id: lane.id,
    cameraId: lane.camera_id ?? '',
    rows: lane.groups.map(toRow),
    order: lane.order,
    batch: String(lane.round_robin_batch),
    afFilter: lane.autofocus_on_filter_change,
  }
}

/** A lane as the API wants it, or an error message. */
function draftToLane(t: TFunction, d: LaneDraft): SequencerLane | string {
  const groups = d.rows.map((r) => parseRow(t, r))
  const bad = groups.findIndex((g) => typeof g === 'string')
  if (bad >= 0) return t('editor.errors.group', { n: bad + 1, error: groups[bad] })
  const batch = Number(d.batch)
  if (d.order === 'round_robin' && (!Number.isInteger(batch) || batch < 1)) return t('editor.errors.batch')
  return {
    ...(d.id ? { id: d.id } : {}),
    camera_id: d.cameraId || null,
    groups: groups as SequencerExposureGroup[],
    order: d.order,
    round_robin_batch: d.order === 'round_robin' ? batch : 1,
    autofocus_on_filter_change: d.afFilter,
  }
}

export function TaskEditor({ entry, onClose }: {
  entry: SequencerQueueEntry | null   // null = new task
  onClose: () => void
}) {
  const { t } = useTranslation('sequencer')
  const connected = useStore((s) => s.connectedDevices)
  const cameras = connected.filter((d) => d.kind === 'camera')

  const base = entry?.task
  const [target, setTarget] = useState<SequencerTargetRef | null>(base?.target ?? null)
  const [name, setName] = useState(base?.name ?? '')
  const [lanes, setLanes] = useState<LaneDraft[]>(
    base ? base.lanes.map(laneToDraft) : [{ key: newKey(), cameraId: '', rows: [{ ...NEW_ROW }], order: 'sequential', batch: '1', afFilter: false }],
  )
  const [slew, setSlew] = useState(base?.slew ?? true)
  const [center, setCenter] = useState(base?.center ?? true)
  const [guide, setGuide] = useState(base?.start_guiding ?? true)
  const [afStart, setAfStart] = useState(base?.autofocus_at_start ?? false)
  const [ditherOn, setDitherOn] = useState(base ? base.dither_every != null : true)
  const [ditherEvery, setDitherEvery] = useState(String(base?.dither_every ?? 1))
  const [subDelay, setSubDelay] = useState(String(base?.sub_delay_s ?? 0))
  const [onError, setOnError] = useState<SequencerTask['on_error']>(base?.on_error ?? 'pause')
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [estimates, setEstimates] = useState<SequencerLaneEstimate[] | null>(null)

  const [paths, setPaths] = useState<OpticalPath[]>([])
  useEffect(() => {
    api.profiles.activeOpticalPaths().then(setPaths).catch(() => setPaths([]))
  }, [])
  const mainCamera = paths.find((p) => p.camera_device_id)?.camera_device_id || cameras[0]?.device_id

  const isCurrent = target?.kind === 'current'
  const every = Number(ditherEvery)

  /** The task as the API wants it, or an error message. */
  const build = (): SequencerTask | string => {
    if (!target) return t('editor.errors.pickTarget')
    const built: SequencerLane[] = []
    for (const [i, d] of lanes.entries()) {
      const lane = draftToLane(t, d)
      if (typeof lane === 'string') return t('editor.errors.laneError', { who: i === 0 ? t('editor.errors.primary') : t('editor.errors.camera', { n: i + 1 }), error: lane })
      built.push(lane)
    }
    if (ditherOn && (!Number.isInteger(every) || every < 1)) return t('editor.errors.dither')
    const delay = Number(subDelay)
    if (!(delay >= 0)) return t('editor.errors.delay')
    return {
      ...(base ?? {}),
      name: name.trim() || null,
      target,
      lanes: built,
      slew, center, start_guiding: guide,
      autofocus_at_start: afStart,
      dither_every: ditherOn ? every : null,
      sub_delay_s: delay,
      on_error: onError,
    }
  }

  // Secondary-lane efficiency from the fit rule, recomputed as the plan changes.
  const draftKey = JSON.stringify([lanes, ditherOn, ditherEvery, target?.name])
  useEffect(() => {
    if (lanes.length < 2) { setEstimates(null); return }
    const task = build()
    if (typeof task === 'string') return
    const timer = setTimeout(() => {
      // Lanes without an id get one server-side; match estimates by position.
      estimate(task).then(setEstimates).catch(() => setEstimates(null))
    }, 350)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draftKey])

  const patchLane = (i: number, patch: Partial<LaneDraft>) =>
    setLanes((ls) => ls.map((l, j) => (j === i ? { ...l, ...patch } : l)))
  const usedCameras = new Set(lanes.map((l) => l.cameraId || mainCamera))
  const freeCamera = cameras.find((c) => !usedCameras.has(c.device_id))

  const save = async () => {
    const task = build()
    if (typeof task === 'string') { setError(task); return }
    setSaving(true)
    setError(null)
    try {
      if (entry) await updateTask(entry.task.id, task)
      else await addTask(task)
      onClose()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const primaryInterval = useMemo(() => {
    const primary = draftToLane(t, lanes[0])
    if (typeof primary === 'string' || !ditherOn || !(every >= 1)) return null
    const frames = primary.groups.reduce((s, g) => s + g.count, 0)
    const avg = primary.groups.reduce((s, g) => s + g.count * g.duration, 0) / (frames || 1)
    return avg * every
  }, [lanes, ditherOn, every, t])

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/60" onClick={onClose}>
      <div
        className="w-full max-w-3xl h-full bg-surface-raised border-l border-surface-border flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-3 border-b border-surface-border">
          <h2 className="text-sm font-semibold text-slate-100">{entry ? t('editor.editTask') : t('editor.newTask')}</h2>
          <Button variant="ghost" size="icon" onClick={onClose} title={t('editor.close')}><X size={16} /></Button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4 flex flex-col gap-6">
          {entry && entry.runtime.lanes.some((l) => l.groups.some((g) => g.frames_done > 0)) && (
            <p className="text-xs text-slate-400 bg-surface-overlay rounded px-3 py-2">
              {t('editor.kept')}
            </p>
          )}

          <Section title={t('editor.target')}>
            <TargetPicker value={target} onChange={setTarget} />
            <label className="flex flex-col gap-1 mt-2">
              <span className="text-xs text-slate-400">{t('editor.taskName')}</span>
              <Input placeholder={target?.name ?? ''} value={name} onChange={(e) => setName(e.target.value)} />
            </label>
          </Section>

          <Section title={lanes.length > 1 ? t('editor.cameras') : t('editor.cameraExposures')}>
            {lanes.length > 1 && (
              <p className="text-xs text-slate-400 mb-3">
                <Trans t={t} i18nKey="editor.multi" components={{ b: <b /> }} />
              </p>
            )}
            <div className="flex flex-col gap-4">
              {lanes.map((draft, i) => (
                <LaneEditor
                  key={draft.key}
                  index={i}
                  draft={draft}
                  count={lanes.length}
                  cameras={cameras}
                  mainCamera={mainCamera}
                  paths={paths}
                  estimate={estimates?.[i] ?? null}
                  primaryInterval={primaryInterval}
                  onChange={(patch) => patchLane(i, patch)}
                  onRemove={() => setLanes((ls) => ls.filter((_, j) => j !== i))}
                  onMakePrimary={() => setLanes((ls) => [ls[i], ...ls.filter((_, j) => j !== i)])}
                />
              ))}
            </div>
            {freeCamera && (
              <Button variant="outline" size="sm" className="self-start mt-3"
                onClick={() => setLanes((ls) => [...ls, {
                  key: newKey(), cameraId: freeCamera.device_id, rows: [{ ...NEW_ROW, duration: '60', count: '30' }],
                  order: 'sequential', batch: '1', afFilter: false,
                }])}>
                <Plus size={12} className="mr-1" /> {t('editor.addCamera', { id: freeCamera.device_id })}
              </Button>
            )}
          </Section>

          <Section title={t('editor.before')}>
            <Toggle label={t('editor.slew')} checked={slew && !isCurrent} disabled={isCurrent} onChange={() => setSlew((v) => !v)} />
            <Toggle label={t('editor.center')} checked={center && !isCurrent} disabled={isCurrent} onChange={() => setCenter((v) => !v)} />
            <Toggle label={t('editor.guide')} checked={guide} onChange={() => setGuide((v) => !v)} />
            <Toggle label={lanes.length > 1 ? t('editor.autofocusAll') : t('editor.autofocus')} checked={afStart} onChange={() => setAfStart((v) => !v)} />
            {isCurrent && <p className="text-xs text-slate-500">{t('editor.currentHint')}</p>}
          </Section>

          <Section title={t('editor.while')}>
            <div className="flex items-center gap-3">
              <ToggleSwitch label={t('editor.dither')} checked={ditherOn} onChange={() => setDitherOn((v) => !v)} />
              <span className="text-sm text-slate-300 whitespace-nowrap">{t('editor.ditherEvery')}</span>
              <div className="w-16">
                <Input inputSize="sm" disabled={!ditherOn} value={ditherEvery} onChange={(e) => setDitherEvery(e.target.value)} />
              </div>
              <span className="text-sm text-slate-300">{lanes.length > 1 ? t('editor.primaryFrames') : t('editor.frames')}</span>
            </div>
            <label className="flex items-center gap-3 mt-2">
              <span className="text-sm text-slate-300">{t('editor.delayLabel')}</span>
              <div className="w-16">
                <Input inputSize="sm" value={subDelay} onChange={(e) => setSubDelay(e.target.value)} />
              </div>
              <span className="text-sm text-slate-300">{t('editor.seconds')}</span>
            </label>
          </Section>

          <Section title={t('editor.fails')}>
            <PillGroup options={['pause', 'skip', 'defer', 'abort'] as const} value={onError} onChange={setOnError}
              formatLabel={(o) => t(`editor.onError.labels.${o}`)} />
            <p className="text-xs text-slate-500 mt-1">{t(`editor.onError.${onError}`)}</p>
          </Section>
        </div>

        <div className="flex items-center gap-3 px-5 py-3 border-t border-surface-border">
          {error && <p className="text-xs text-status-error flex-1">{error}</p>}
          <div className="ml-auto flex gap-2">
            <Button variant="ghost" onClick={onClose}>{t('editor.cancel')}</Button>
            <Button onClick={save} disabled={saving || !target}>{entry ? t('editor.saveChanges') : t('editor.addToQueue')}</Button>
          </div>
        </div>
      </div>
    </div>
  )
}

function LaneEditor({
  index, draft, count, cameras, mainCamera, paths, estimate, primaryInterval, onChange, onRemove, onMakePrimary,
}: {
  index: number
  draft: LaneDraft
  count: number
  cameras: ConnectedDevice[]
  mainCamera: string | undefined
  paths: OpticalPath[]
  estimate: SequencerLaneEstimate | null
  primaryInterval: number | null
  onChange: (patch: Partial<LaneDraft>) => void
  onRemove: () => void
  onMakePrimary: () => void
}) {
  const { t } = useTranslation('sequencer')
  const { t: tc } = useTranslation()
  const filterWheels = useStore((s) => s.connectedDevices.filter((d) => d.kind === 'filter_wheel'))
  const camera = draft.cameraId || mainCamera
  const wheelId = useMemo(() => {
    const path = paths.find((p) => p.camera_device_id === camera)
    if (path) return path.filter_wheel_device_id
    return filterWheels.length === 1 ? filterWheels[0].device_id : null
  }, [paths, camera, filterWheels])
  const [filterNames, setFilterNames] = useState<string[]>([])
  useEffect(() => {
    if (!wheelId) { setFilterNames([]); return }
    api.filterWheel.status(wheelId).then((s) => setFilterNames(s.filter_names ?? [])).catch(() => setFilterNames([]))
  }, [wheelId])

  const rows = draft.rows
  const parsed = rows.map((r) => parseRow(t, r))
  const totalS = parsed.reduce((s, g) => s + (typeof g === 'string' ? 0 : g.count * g.duration), 0)
  const setRows = (next: GroupRow[]) => onChange({ rows: next })
  const patchRow = (i: number, patch: Partial<GroupRow>) => setRows(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)))
  const moveRow = (i: number, d: -1 | 1) => {
    const j = i + d
    if (j < 0 || j >= rows.length) return
    const copy = [...rows]
    ;[copy[i], copy[j]] = [copy[j], copy[i]]
    setRows(copy)
  }
  const primary = index === 0

  return (
    <div className={`rounded border px-3 py-3 ${count > 1 ? 'border-surface-border bg-surface' : 'border-transparent px-0 py-0'}`}>
      {count > 1 && (
        <div className="flex items-center gap-2 mb-2">
          <span className={`text-xs font-medium ${primary ? 'text-amber-300' : 'text-slate-400'}`}>
            {primary ? <span className="inline-flex items-center gap-1"><Crown size={12} /> {t('editor.lane.primary')}</span> : t('editor.errors.camera', { n: index + 1 })}
          </span>
          <span className="text-xs text-slate-500">{t('editor.lane.exposureTotal', { time: fmtSeconds(totalS) })}</span>
          <div className="ml-auto flex gap-1">
            {!primary && <Button variant="ghost" size="sm" onClick={onMakePrimary}>{t('editor.lane.makePrimary')}</Button>}
            <Button variant="ghost" size="sm" onClick={onRemove} title={t('editor.lane.remove')}><Trash2 size={12} /></Button>
          </div>
        </div>
      )}
      <select
        value={draft.cameraId}
        onChange={(e) => onChange({ cameraId: e.target.value })}
        className="bg-surface border border-surface-border rounded-lg px-3 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent"
      >
        {primary && <option value="">{mainCamera ? t('editor.lane.mainNamed', { id: mainCamera }) : t('editor.lane.main')}</option>}
        {cameras.map((c) => <option key={c.device_id} value={c.device_id}>{c.device_id}</option>)}
      </select>
      {!wheelId && <span className="text-xs text-slate-500 ml-2">{t('editor.lane.noWheel')}</span>}

      {!primary && estimate && (
        <EfficiencyNote estimate={estimate} primaryInterval={primaryInterval} />
      )}

      <div className="overflow-x-auto mt-2">
        <table className="w-full text-xs">
          <thead className="text-slate-500">
            <tr className="text-left">
              <th className="font-normal pb-1 pr-2">{t('editor.lane.filter')}</th>
              <th className="font-normal pb-1 pr-2">{t('editor.lane.exposure')}</th>
              <th className="font-normal pb-1 pr-2">{t('editor.lane.count')}</th>
              <th className="font-normal pb-1 pr-2">{t('editor.lane.gain')}</th>
              <th className="font-normal pb-1 pr-2">{t('editor.lane.bin')}</th>
              <th className="font-normal pb-1 pr-2">{t('editor.lane.type')}</th>
              <th className="font-normal pb-1 pr-2 text-right">{t('editor.lane.total')}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
              const g = parsed[i]
              const knownFilter = !r.filter_name || filterNames.includes(r.filter_name)
              return (
                <tr key={i} className="align-middle">
                  <td className="pr-2 py-1">
                    <select value={r.filter_name} onChange={(e) => patchRow(i, { filter_name: e.target.value })}
                      className={`bg-surface-overlay border rounded px-2 py-1 text-xs text-slate-200 w-24 ${knownFilter ? 'border-surface-border' : 'border-status-error'}`}
                      title={knownFilter ? undefined : t('editor.lane.badFilter')}>
                      <option value="">—</option>
                      {filterNames.map((f) => <option key={f} value={f}>{f}</option>)}
                      {!knownFilter && <option value={r.filter_name}>{r.filter_name} (?)</option>}
                    </select>
                  </td>
                  <td className="pr-2 py-1 w-24"><Input inputSize="sm" value={r.duration} onChange={(e) => patchRow(i, { duration: e.target.value })} /></td>
                  <td className="pr-2 py-1 w-20"><Input inputSize="sm" value={r.count} onChange={(e) => patchRow(i, { count: e.target.value })} /></td>
                  <td className="pr-2 py-1 w-20"><Input inputSize="sm" placeholder="—" value={r.gain} onChange={(e) => patchRow(i, { gain: e.target.value })} /></td>
                  <td className="pr-2 py-1">
                    <select value={r.binning} onChange={(e) => patchRow(i, { binning: Number(e.target.value) })}
                      className="bg-surface border border-surface-border rounded-lg px-1 py-1 text-xs text-slate-200">
                      {[1, 2, 3, 4].map((b) => <option key={b} value={b}>{b}×{b}</option>)}
                    </select>
                  </td>
                  <td className="pr-2 py-1">
                    <select value={r.frame_type} onChange={(e) => patchRow(i, { frame_type: e.target.value as GroupRow['frame_type'] })}
                      className="bg-surface border border-surface-border rounded-lg px-1 py-1 text-xs text-slate-200">
                      {(['light', 'dark', 'flat', 'bias'] as const).map((ft) => <option key={ft} value={ft}>{tc(`frameType.${ft}`)}</option>)}
                    </select>
                  </td>
                  <td className="pr-2 py-1 text-right font-mono text-slate-400 whitespace-nowrap">
                    {typeof g === 'string' ? <span className="text-status-error" title={g}>!</span> : fmtSeconds(g.count * g.duration)}
                  </td>
                  <td className="py-1 whitespace-nowrap">
                    <button type="button" className="p-1 text-slate-500 hover:text-slate-200 disabled:opacity-30" disabled={i === 0} onClick={() => moveRow(i, -1)} title={t('editor.lane.moveUp')}><ArrowUp size={12} /></button>
                    <button type="button" className="p-1 text-slate-500 hover:text-slate-200 disabled:opacity-30" disabled={i === rows.length - 1} onClick={() => moveRow(i, 1)} title={t('editor.lane.moveDown')}><ArrowDown size={12} /></button>
                    <button type="button" className="p-1 text-slate-500 hover:text-status-error disabled:opacity-30" disabled={rows.length === 1}
                      onClick={() => setRows(rows.filter((_, j) => j !== i))} title={t('editor.lane.removeRow')}><Trash2 size={12} /></button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <div className="flex items-end gap-4 mt-2 flex-wrap">
        <Button variant="outline" size="sm" onClick={() => setRows([...rows, { ...(rows[rows.length - 1] ?? NEW_ROW), filter_name: '' }])}>
          <Plus size={12} className="mr-1" /> {t('editor.lane.addGroup')}
        </Button>
        <PillGroup label={t('editor.lane.order')} options={['sequential', 'round_robin'] as const} value={draft.order}
          onChange={(o) => onChange({ order: o })}
          formatLabel={(o) => (o === 'sequential' ? t('editor.lane.sequential') : t('editor.lane.roundRobin'))} />
        {draft.order === 'round_robin' && (
          <label className="flex flex-col gap-1 w-28">
            <span className="text-xs text-slate-400">{t('editor.lane.perTurn')}</span>
            <Input inputSize="sm" value={draft.batch} onChange={(e) => onChange({ batch: e.target.value })} />
          </label>
        )}
        <div className="flex items-center gap-2 pb-1">
          <ToggleSwitch label={t('editor.lane.afFilter')} checked={draft.afFilter} onChange={() => onChange({ afFilter: !draft.afFilter })} />
          <span className="text-xs text-slate-300">{t('editor.lane.afFilter')}</span>
        </div>
      </div>
    </div>
  )
}

function EfficiencyNote({ estimate, primaryInterval }: {
  estimate: SequencerLaneEstimate
  primaryInterval: number | null
}) {
  const { t } = useTranslation('sequencer')
  if (!estimate.can_start) {
    return (
      <p className="text-xs text-status-error mt-2">
        {t('editor.efficiency.cannotStart', { longest: estimate.longest_s, interval: primaryInterval ? t('editor.efficiency.approx', { time: fmtSeconds(primaryInterval) }) : '' })}
      </p>
    )
  }
  const pct = Math.round(estimate.efficiency * 100)
  const tone = estimate.efficiency >= 0.95 ? 'text-emerald-300' : estimate.efficiency >= 0.8 ? 'text-slate-300' : 'text-yellow-400'
  return (
    <p className={`text-xs mt-2 ${tone}`}>
      {t('editor.efficiency.exposes', { pct })}
      {primaryInterval ? t('editor.efficiency.fitted', { time: fmtSeconds(primaryInterval) }) : ''}
      {estimate.efficiency < 0.8 ? t('editor.efficiency.shorter') : t('editor.efficiency.end')}
      {t('editor.efficiency.total', { time: fmtSeconds(estimate.wall_s) })}
    </p>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col">
      <h3 className="font-medium text-slate-500 label-caps mb-2">{title}</h3>
      {children}
    </section>
  )
}

function Toggle({ label, checked, onChange, disabled }: {
  label: string
  checked: boolean
  onChange: () => void
  disabled?: boolean
}) {
  return (
    <div className="flex items-center gap-3 py-1">
      <ToggleSwitch label={label} checked={checked} onChange={onChange} disabled={disabled} />
      <span className={`text-sm ${disabled ? 'text-slate-500' : 'text-slate-300'}`}>{label}</span>
    </div>
  )
}
