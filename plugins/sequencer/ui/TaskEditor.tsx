// Drawer to create or edit a task: target, camera, exposure groups, options.
import { useEffect, useMemo, useState } from 'react'
import { ArrowDown, ArrowUp, Plus, Trash2, X } from 'lucide-react'
import { api } from '@/api/client'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { PillGroup } from '@/components/ui/pill-group'
import { ToggleSwitch } from '@/components/ui/toggle-switch'
import { useStore } from '@/store'
import type {
  OpticalPath,
  SequencerExposureGroup,
  SequencerQueueEntry,
  SequencerTargetRef,
  SequencerTask,
} from '@/api/types'
import { addTask, updateTask } from './api'
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

const ON_ERROR_HELP: Record<SequencerTask['on_error'], string> = {
  pause: 'Pause the whole run; Resume retries the failed step.',
  skip: 'Mark this task failed and go on with the next one.',
  defer: 'Set this task aside (resumable later) and go on with the next one.',
  abort: 'Stop the whole run.',
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

function parseRow(r: GroupRow): SequencerExposureGroup | string {
  const duration = Number(r.duration)
  const count = Number(r.count)
  if (!(duration > 0)) return 'Duration must be a positive number of seconds'
  if (!Number.isInteger(count) || count < 1) return 'Count must be a whole number ≥ 1'
  let gain: number | null = null
  if (r.gain.trim() !== '') {
    gain = Number(r.gain)
    if (!Number.isInteger(gain) || gain < 0) return 'Gain must be a whole number ≥ 0 (or empty)'
  }
  return {
    filter_name: r.filter_name || null,
    duration, count, gain,
    binning: r.binning,
    frame_type: r.frame_type,
  }
}

const NEW_ROW: GroupRow = { filter_name: '', duration: '300', count: '10', gain: '', binning: 1, frame_type: 'light' }

export function TaskEditor({ entry, onClose }: {
  entry: SequencerQueueEntry | null   // null = new task
  onClose: () => void
}) {
  const connected = useStore((s) => s.connectedDevices)
  const cameras = connected.filter((d) => d.kind === 'camera')
  const filterWheels = connected.filter((d) => d.kind === 'filter_wheel')

  const base = entry?.task
  const lane = base?.lanes[0]
  const [target, setTarget] = useState<SequencerTargetRef | null>(base?.target ?? null)
  const [name, setName] = useState(base?.name ?? '')
  const [cameraId, setCameraId] = useState(lane?.camera_id ?? '')
  const [rows, setRows] = useState<GroupRow[]>(lane ? lane.groups.map(toRow) : [{ ...NEW_ROW }])
  const [order, setOrder] = useState(lane?.order ?? 'sequential')
  const [batch, setBatch] = useState(String(lane?.round_robin_batch ?? 1))
  const [slew, setSlew] = useState(base?.slew ?? true)
  const [center, setCenter] = useState(base?.center ?? true)
  const [guide, setGuide] = useState(base?.start_guiding ?? true)
  const [afStart, setAfStart] = useState(base?.autofocus_at_start ?? false)
  const [afFilter, setAfFilter] = useState(lane?.autofocus_on_filter_change ?? false)
  const [ditherOn, setDitherOn] = useState(base ? base.dither_every != null : true)
  const [ditherEvery, setDitherEvery] = useState(String(base?.dither_every ?? 1))
  const [subDelay, setSubDelay] = useState(String(base?.sub_delay_s ?? 0))
  const [onError, setOnError] = useState<SequencerTask['on_error']>(base?.on_error ?? 'pause')
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  // Filter names of the chosen camera's wheel, from the profile's optical paths.
  const [paths, setPaths] = useState<OpticalPath[]>([])
  const [filterNames, setFilterNames] = useState<string[]>([])
  useEffect(() => {
    api.profiles.activeOpticalPaths().then(setPaths).catch(() => setPaths([]))
  }, [])
  const effectiveCamera = cameraId || paths.find((p) => p.camera_device_id)?.camera_device_id || cameras[0]?.device_id
  const wheelId = useMemo(() => {
    const path = paths.find((p) => p.camera_device_id === effectiveCamera)
    if (path) return path.filter_wheel_device_id
    return filterWheels.length === 1 ? filterWheels[0].device_id : null
  }, [paths, effectiveCamera, filterWheels])
  useEffect(() => {
    if (!wheelId) { setFilterNames([]); return }
    api.filterWheel.status(wheelId).then((s) => setFilterNames(s.filter_names ?? [])).catch(() => setFilterNames([]))
  }, [wheelId])

  const parsed = rows.map(parseRow)
  const totalS = parsed.reduce((s, g) => s + (typeof g === 'string' ? 0 : g.count * g.duration), 0)
  const isCurrent = target?.kind === 'current'

  const patchRow = (i: number, patch: Partial<GroupRow>) =>
    setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)))
  const moveRow = (i: number, d: -1 | 1) =>
    setRows((rs) => {
      const j = i + d
      if (j < 0 || j >= rs.length) return rs
      const copy = [...rs]
      ;[copy[i], copy[j]] = [copy[j], copy[i]]
      return copy
    })

  const save = async () => {
    if (!target) { setError('Pick a target first'); return }
    const bad = parsed.findIndex((g) => typeof g === 'string')
    if (bad >= 0) { setError(`Group ${bad + 1}: ${parsed[bad]}`); return }
    const every = Number(ditherEvery)
    if (ditherOn && (!Number.isInteger(every) || every < 1)) { setError('Dither every: a whole number ≥ 1'); return }
    const batchN = Number(batch)
    if (order === 'round_robin' && (!Number.isInteger(batchN) || batchN < 1)) { setError('Batch: a whole number ≥ 1'); return }
    const delay = Number(subDelay)
    if (!(delay >= 0)) { setError('Delay between frames: seconds ≥ 0'); return }

    const task: SequencerTask = {
      ...(base ?? {}),
      name: name.trim() || null,
      target,
      lanes: [{
        ...(lane ?? {}),
        camera_id: cameraId || null,
        groups: parsed as SequencerExposureGroup[],
        order,
        round_robin_batch: order === 'round_robin' ? batchN : 1,
        autofocus_on_filter_change: afFilter,
      }],
      slew, center, start_guiding: guide,
      autofocus_at_start: afStart,
      dither_every: ditherOn ? every : null,
      sub_delay_s: delay,
      on_error: onError,
    }
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

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/60" onClick={onClose}>
      <div
        className="w-full max-w-2xl h-full bg-surface-raised border-l border-surface-border flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-3 border-b border-surface-border">
          <h2 className="text-sm font-semibold text-slate-100">{entry ? 'Edit task' : 'New task'}</h2>
          <Button variant="ghost" size="icon" onClick={onClose} title="Close"><X size={16} /></Button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4 flex flex-col gap-6">
          {entry && entry.runtime.lanes[0]?.groups.some((g) => g.frames_done > 0) && (
            <p className="text-xs text-slate-400 bg-surface-overlay rounded px-3 py-2">
              Frames already taken are kept for groups whose filter, duration, gain, binning and
              type stay the same; changing any of those restarts that group from zero.
            </p>
          )}

          <Section title="Target">
            <TargetPicker value={target} onChange={setTarget} />
            <label className="flex flex-col gap-1 mt-2">
              <span className="text-xs text-slate-400">Task name (optional)</span>
              <Input placeholder={target?.name ?? ''} value={name} onChange={(e) => setName(e.target.value)} />
            </label>
          </Section>

          <Section title="Camera">
            <select
              value={cameraId}
              onChange={(e) => setCameraId(e.target.value)}
              className="bg-surface-overlay border border-surface-border rounded px-3 py-1.5 text-sm text-slate-200 focus:outline-none focus:ring-1 focus:ring-accent"
            >
              <option value="">Main camera{effectiveCamera && !cameraId ? ` (${effectiveCamera})` : ''}</option>
              {cameras.map((c) => <option key={c.device_id} value={c.device_id}>{c.device_id}</option>)}
            </select>
            {!wheelId && <p className="text-xs text-slate-500 mt-1">This camera has no filter wheel.</p>}
          </Section>

          <Section title={`Exposures — ${fmtSeconds(totalS)} total`}>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="text-slate-500">
                  <tr className="text-left">
                    <th className="font-normal pb-1 pr-2">Filter</th>
                    <th className="font-normal pb-1 pr-2">Exposure (s)</th>
                    <th className="font-normal pb-1 pr-2">Count</th>
                    <th className="font-normal pb-1 pr-2">Gain</th>
                    <th className="font-normal pb-1 pr-2">Bin</th>
                    <th className="font-normal pb-1 pr-2">Type</th>
                    <th className="font-normal pb-1 pr-2 text-right">Total</th>
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
                          <select
                            value={r.filter_name}
                            onChange={(e) => patchRow(i, { filter_name: e.target.value })}
                            className={`bg-surface-overlay border rounded px-2 py-1 text-xs text-slate-200 w-24
                              ${knownFilter ? 'border-surface-border' : 'border-status-error'}`}
                            title={knownFilter ? undefined : 'Not a slot name of this camera\'s filter wheel'}
                          >
                            <option value="">—</option>
                            {filterNames.map((f) => <option key={f} value={f}>{f}</option>)}
                            {!knownFilter && <option value={r.filter_name}>{r.filter_name} (?)</option>}
                          </select>
                        </td>
                        <td className="pr-2 py-1 w-24">
                          <Input inputSize="sm" value={r.duration} onChange={(e) => patchRow(i, { duration: e.target.value })} />
                        </td>
                        <td className="pr-2 py-1 w-20">
                          <Input inputSize="sm" value={r.count} onChange={(e) => patchRow(i, { count: e.target.value })} />
                        </td>
                        <td className="pr-2 py-1 w-20">
                          <Input inputSize="sm" placeholder="—" value={r.gain} onChange={(e) => patchRow(i, { gain: e.target.value })} />
                        </td>
                        <td className="pr-2 py-1">
                          <select
                            value={r.binning}
                            onChange={(e) => patchRow(i, { binning: Number(e.target.value) })}
                            className="bg-surface-overlay border border-surface-border rounded px-1 py-1 text-xs text-slate-200"
                          >
                            {[1, 2, 3, 4].map((b) => <option key={b} value={b}>{b}×{b}</option>)}
                          </select>
                        </td>
                        <td className="pr-2 py-1">
                          <select
                            value={r.frame_type}
                            onChange={(e) => patchRow(i, { frame_type: e.target.value as GroupRow['frame_type'] })}
                            className="bg-surface-overlay border border-surface-border rounded px-1 py-1 text-xs text-slate-200"
                          >
                            {(['light', 'dark', 'flat', 'bias'] as const).map((t) => <option key={t} value={t}>{t}</option>)}
                          </select>
                        </td>
                        <td className="pr-2 py-1 text-right font-mono text-slate-400 whitespace-nowrap">
                          {typeof g === 'string' ? <span className="text-status-error" title={g}>!</span> : fmtSeconds(g.count * g.duration)}
                        </td>
                        <td className="py-1 whitespace-nowrap">
                          <button type="button" className="p-1 text-slate-500 hover:text-slate-200 disabled:opacity-30"
                            disabled={i === 0} onClick={() => moveRow(i, -1)} title="Move up"><ArrowUp size={12} /></button>
                          <button type="button" className="p-1 text-slate-500 hover:text-slate-200 disabled:opacity-30"
                            disabled={i === rows.length - 1} onClick={() => moveRow(i, 1)} title="Move down"><ArrowDown size={12} /></button>
                          <button type="button" className="p-1 text-slate-500 hover:text-status-error disabled:opacity-30"
                            disabled={rows.length === 1} onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))}
                            title="Remove"><Trash2 size={12} /></button>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
            <Button variant="outline" size="sm" className="self-start mt-2"
              onClick={() => setRows((rs) => [...rs, { ...(rs[rs.length - 1] ?? NEW_ROW), filter_name: '' }])}>
              <Plus size={12} className="mr-1" /> Add group
            </Button>
            <div className="flex items-end gap-4 mt-3">
              <PillGroup
                label="Order"
                options={['sequential', 'round_robin'] as const}
                value={order}
                onChange={setOrder}
                formatLabel={(o) => (o === 'sequential' ? 'Group by group' : 'Round robin')}
              />
              {order === 'round_robin' && (
                <label className="flex flex-col gap-1 w-28">
                  <span className="text-xs text-slate-400">Frames per turn</span>
                  <Input inputSize="sm" value={batch} onChange={(e) => setBatch(e.target.value)} />
                </label>
              )}
            </div>
          </Section>

          <Section title="Before imaging">
            <Toggle label="Slew to the target" checked={slew && !isCurrent} disabled={isCurrent} onChange={() => setSlew((v) => !v)} />
            <Toggle label="Center with plate solving" checked={center && !isCurrent} disabled={isCurrent} onChange={() => setCenter((v) => !v)} />
            <Toggle label="Start guiding (wait for settle)" checked={guide} onChange={() => setGuide((v) => !v)} />
            <Toggle label="Autofocus" checked={afStart} onChange={() => setAfStart((v) => !v)} />
            {isCurrent && <p className="text-xs text-slate-500">"Mount pointing" targets never slew or center.</p>}
          </Section>

          <Section title="While imaging">
            <Toggle label="Autofocus after each filter change" checked={afFilter} onChange={() => setAfFilter((v) => !v)} />
            <div className="flex items-center gap-3">
              <ToggleSwitch label="Dither" checked={ditherOn} onChange={() => setDitherOn((v) => !v)} />
              <span className="text-sm text-slate-300 whitespace-nowrap">Dither every</span>
              <div className="w-16">
                <Input inputSize="sm" disabled={!ditherOn} value={ditherEvery}
                  onChange={(e) => setDitherEvery(e.target.value)} />
              </div>
              <span className="text-sm text-slate-300">frame(s)</span>
            </div>
            <label className="flex items-center gap-3 mt-2">
              <span className="text-sm text-slate-300">Delay between frames</span>
              <div className="w-16">
                <Input inputSize="sm" value={subDelay} onChange={(e) => setSubDelay(e.target.value)} />
              </div>
              <span className="text-sm text-slate-300">s</span>
            </label>
          </Section>

          <Section title="If a step fails">
            <PillGroup options={['pause', 'skip', 'defer', 'abort'] as const} value={onError} onChange={setOnError} />
            <p className="text-xs text-slate-500 mt-1">{ON_ERROR_HELP[onError]}</p>
          </Section>
        </div>

        <div className="flex items-center gap-3 px-5 py-3 border-t border-surface-border">
          {error && <p className="text-xs text-status-error flex-1">{error}</p>}
          <div className="ml-auto flex gap-2">
            <Button variant="ghost" onClick={onClose}>Cancel</Button>
            <Button onClick={save} disabled={saving || !target}>{entry ? 'Save changes' : 'Add to queue'}</Button>
          </div>
        </div>
      </div>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col">
      <h3 className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-2">{title}</h3>
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
