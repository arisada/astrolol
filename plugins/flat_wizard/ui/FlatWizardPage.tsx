import { useCallback, useEffect, useRef, useState } from 'react'
import { Sun, StopCircle } from 'lucide-react'
import { api } from '@/api/client'
import * as flatWizardApi from './api'
import { useStore } from '@/store'
import { Button } from '@/components/ui/button'
import { SidebarSection } from '@/components/ui/card'
import { DurationStepper } from '@/components/ui/duration-stepper'
import { Input } from '@/components/ui/input'
import { PillGroup } from '@/components/ui/pill-group'
import { StatusPill } from '@/components/ui/badge'
import type { StatusPillVariant } from '@/components/ui/badge'
import type {
  FilterWheelStatus,
  FlatFilterResult,
  FlatWizardConfig,
  FlatWizardFilterSpec,
  FlatWizardRun,
  OpticalPath,
} from '@/api/types'
import type { FlatWizardLiveState } from './state'

const SEED_DURATION_STEPS = [0.001, 0.01, 0.1, 0.5, 1, 2, 3, 5, 8, 10, 15, 20, 30]
const MAX_DURATION_STEPS = [1, 2, 5, 10, 15, 20, 30, 45, 60, 90, 120]
const BINNINGS = [1, 2, 3, 4]
const DEFAULT_COUNT = 20

interface AdvancedSettings {
  target_pct: number
  tolerance_pct: number
  saturation_pct: number
  binning: number
  gain: number | null
  seed_duration: number
  max_duration: number
  max_attempts: number
}

const DEFAULT_SETTINGS: AdvancedSettings = {
  target_pct: 50,
  tolerance_pct: 5,
  saturation_pct: 95,
  binning: 1,
  gain: null,
  seed_duration: 0.01,
  max_duration: 30,
  max_attempts: 8,
}

const RUN_PILL_VARIANT: Record<FlatWizardRun['status'], StatusPillVariant> = {
  running: 'amber', completed: 'green', failed: 'red', aborted: 'slate',
}

const RESULT_PILL_VARIANT: Record<FlatFilterResult['status'], StatusPillVariant> = {
  solved: 'green', failed: 'red',
}

export function FlatWizardPage() {
  const connectedDevices = useStore((s) => s.connectedDevices)
  const live = useStore((s) => s.pluginStates['flat_wizard'] as FlatWizardLiveState | null | undefined)

  const cameras = connectedDevices.filter((d) => d.kind === 'camera')
  const filterWheels = connectedDevices.filter((d) => d.kind === 'filter_wheel')

  const [cameraId, setCameraId] = useState('')
  const [settings, setSettings] = useState<AdvancedSettings>(DEFAULT_SETTINGS)
  const [filterWheelStatus, setFilterWheelStatus] = useState<FilterWheelStatus | null>(null)
  const [counts, setCounts] = useState<Record<string, number>>({})
  const [singleCount, setSingleCount] = useState(DEFAULT_COUNT)

  const patchSettings = useCallback(<K extends keyof AdvancedSettings>(key: K, value: AdvancedSettings[K]) => {
    setSettings((s) => ({ ...s, [key]: value }))
  }, [])

  // Resolve this camera's filter wheel from the active profile's equipment tree —
  // same approach as the autofocus/imaging pages, so a guide camera with no filter
  // wheel never offers one just because some other camera on the rig has one.
  const [opticalPaths, setOpticalPaths] = useState<OpticalPath[]>([])
  useEffect(() => {
    api.profiles.activeOpticalPaths().then(setOpticalPaths).catch(() => setOpticalPaths([]))
  }, [])

  const opticalPath = cameraId ? (opticalPaths.find((p) => p.camera_device_id === cameraId) ?? null) : null
  const resolvedFilterWheel = opticalPath
    ? filterWheels.find((d) => d.device_id === opticalPath.filter_wheel_device_id) ?? null
    : null
  const filterWheelCandidates = opticalPath ? (resolvedFilterWheel ? [resolvedFilterWheel] : []) : filterWheels
  const [manualFilterWheelId, setManualFilterWheelId] = useState('')
  const filterWheelId = opticalPath ? (resolvedFilterWheel?.device_id ?? null) : (manualFilterWheelId || null)

  useEffect(() => {
    if (!cameraId && cameras.length > 0) setCameraId(cameras[0].device_id)
  }, [cameras])  // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!filterWheelId) { setFilterWheelStatus(null); return }
    api.filterWheel.status(filterWheelId).then(setFilterWheelStatus).catch(() => setFilterWheelStatus(null))
  }, [filterWheelId])

  // Default every filter in the wheel to DEFAULT_COUNT the first time it's seen;
  // a filter the user has zeroed out stays zeroed when the wheel is re-read.
  useEffect(() => {
    const names = filterWheelStatus?.filter_names ?? []
    setCounts((prev) => {
      const next: Record<string, number> = {}
      for (const name of names) next[name] = prev[name] ?? DEFAULT_COUNT
      return next
    })
  }, [filterWheelStatus])

  // ── Run state ──────────────────────────────────────────────────────────────
  const [run, setRun] = useState<FlatWizardRun | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const fetchRun = useCallback(async () => {
    try {
      const r = await flatWizardApi.run()
      setRun(r)
      if (r.status !== 'running') {
        setBusy(false)
        if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
      }
    } catch { /* 404 = no run yet */ }
  }, [])

  useEffect(() => {
    flatWizardApi.run().then((r) => {
      setRun(r)
      if (r.status === 'running') {
        setBusy(true)
        pollRef.current = setInterval(fetchRun, 1500)
      }
    }).catch(() => {})
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [fetchRun])

  const filters: FlatWizardFilterSpec[] = filterWheelId
    ? (filterWheelStatus?.filter_names ?? [])
        .map((name) => ({ filter_name: name, count: counts[name] ?? 0 }))
        .filter((f) => f.count > 0)
    : [{ filter_name: null, count: singleCount }]

  const handleStart = useCallback(async () => {
    if (!cameraId) { setError('A camera must be connected.'); return }
    if (filters.length === 0) { setError('Set a frame count for at least one filter.'); return }
    setError(null)
    setBusy(true)
    setRun(null)

    const config: FlatWizardConfig = {
      camera_id: cameraId,
      filter_wheel_id: filterWheelId,
      filters,
      ...settings,
    }

    try {
      const r = await flatWizardApi.start(config)
      setRun(r)
      pollRef.current = setInterval(fetchRun, 1500)
    } catch (err) {
      setBusy(false)
      setError(err instanceof Error ? err.message : 'Failed to start the flat wizard')
    }
  }, [cameraId, filterWheelId, filters, settings, fetchRun])

  const handleAbort = useCallback(async () => {
    try { await flatWizardApi.abort(); await fetchRun() }
    catch { setBusy(false) }
  }, [fetchRun])

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className="flex flex-col h-full overflow-y-auto bg-surface-bg">
      <div className="flex items-center justify-between px-4 py-3 border-b border-surface-border">
        <div className="flex items-center gap-2 text-slate-200">
          <Sun size={16} />
          <h2 className="text-sm font-medium">Flat Wizard</h2>
          {run && <StatusPill variant={RUN_PILL_VARIANT[run.status]} status={run.status} />}
        </div>
        {busy ? (
          <Button size="sm" variant="danger" onClick={handleAbort}>
            <StopCircle size={14} className="mr-1.5" /> Abort
          </Button>
        ) : (
          <Button size="sm" onClick={handleStart} disabled={!cameraId || filters.length === 0}>
            Solve &amp; Queue Flats
          </Button>
        )}
      </div>

      {error && <div className="px-4 py-2 text-xs text-rose-400 bg-rose-500/10 border-b border-rose-500/20">{error}</div>}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-0 flex-1">
        <div>
          <SidebarSection title="Camera">
            {cameras.length === 0 ? (
              <span className="text-xs text-slate-600">No camera connected</span>
            ) : (
              <select value={cameraId} onChange={(e) => setCameraId(e.target.value)} disabled={busy}
                className="w-full rounded bg-surface-overlay border border-surface-border px-2 py-1.5 text-xs text-slate-200 focus:outline-none focus:ring-1 focus:ring-accent">
                {cameras.map((d) => <option key={d.device_id} value={d.device_id}>{d.device_id}</option>)}
              </select>
            )}
          </SidebarSection>

          <SidebarSection title="Filter Wheel">
            {opticalPath ? (
              resolvedFilterWheel
                ? <span className="text-xs text-slate-300 font-mono">{resolvedFilterWheel.device_id}</span>
                : <span className="text-xs text-slate-600">No filter wheel on this camera's optical path — single pass</span>
            ) : filterWheelCandidates.length === 0 ? (
              <span className="text-xs text-slate-600">No filter wheel connected — single pass</span>
            ) : (
              <select value={manualFilterWheelId} onChange={(e) => setManualFilterWheelId(e.target.value)} disabled={busy}
                className="w-full rounded bg-surface-overlay border border-surface-border px-2 py-1.5 text-xs text-slate-200 focus:outline-none focus:ring-1 focus:ring-accent">
                <option value="">None (single pass)</option>
                {filterWheelCandidates.map((d) => <option key={d.device_id} value={d.device_id}>{d.device_id}</option>)}
              </select>
            )}
          </SidebarSection>

          <SidebarSection title="Frames per filter">
            {filterWheelId && filterWheelStatus?.filter_names.length ? (
              <div className="flex flex-col gap-2">
                {filterWheelStatus.filter_names.map((name) => (
                  <div key={name} className="flex items-center gap-2">
                    <span className="text-xs text-slate-300 font-mono w-16 truncate" title={name}>{name}</span>
                    <Input
                      inputSize="sm" type="number" min={0} disabled={busy}
                      value={counts[name] ?? 0}
                      onChange={(e) => setCounts((c) => ({ ...c, [name]: Math.max(0, parseInt(e.target.value, 10) || 0) }))}
                      className="w-20"
                    />
                    <span className="text-xs text-slate-500">frames</span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="flex items-center gap-2">
                <span className="text-xs text-slate-400">Count</span>
                <Input
                  inputSize="sm" type="number" min={1} disabled={busy}
                  value={singleCount}
                  onChange={(e) => setSingleCount(Math.max(1, parseInt(e.target.value, 10) || 1))}
                  className="w-20"
                />
                <span className="text-xs text-slate-500">frames</span>
              </div>
            )}
          </SidebarSection>

          <SidebarSection title="Target">
            <div className="flex flex-col gap-3">
              <div className="flex items-center gap-2">
                <span className="text-xs text-slate-400 w-36">Target full well (mean)</span>
                <Input
                  inputSize="sm" type="number" min={1} max={99} disabled={busy}
                  value={settings.target_pct}
                  onChange={(e) => patchSettings('target_pct', Math.min(99, Math.max(1, parseFloat(e.target.value) || 0)))}
                  className="w-16"
                />
                <span className="text-xs text-slate-500">%</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs text-slate-400 w-28">Tolerance</span>
                <Input
                  inputSize="sm" type="number" min={1} max={40} disabled={busy}
                  value={settings.tolerance_pct}
                  onChange={(e) => patchSettings('tolerance_pct', Math.min(40, Math.max(1, parseFloat(e.target.value) || 0)))}
                  className="w-16"
                />
                <span className="text-xs text-slate-500">% ±</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs text-slate-400 w-28">Saturation guard</span>
                <Input
                  inputSize="sm" type="number" min={50} max={100} disabled={busy}
                  value={settings.saturation_pct}
                  onChange={(e) => patchSettings('saturation_pct', Math.min(100, Math.max(50, parseFloat(e.target.value) || 0)))}
                  className="w-16"
                />
                <span className="text-xs text-slate-500">% — treat as clipped above this</span>
              </div>
            </div>
          </SidebarSection>

          <SidebarSection title="Trial exposures">
            <div className="flex flex-col gap-3">
              <DurationStepper steps={SEED_DURATION_STEPS} value={settings.seed_duration}
                onChange={(v) => patchSettings('seed_duration', v)} label="Starting duration" />
              <DurationStepper steps={MAX_DURATION_STEPS} value={settings.max_duration}
                onChange={(v) => patchSettings('max_duration', v)} label="Max duration (safety cap)" />
              <PillGroup options={BINNINGS} value={settings.binning}
                onChange={(v) => patchSettings('binning', v)} label="Binning" />
              <div className="flex items-center gap-2">
                <span className="text-xs text-slate-400 w-28">Gain</span>
                <Input
                  inputSize="sm" type="number" min={0} disabled={busy}
                  value={settings.gain ?? ''}
                  placeholder="driver default"
                  onChange={(e) => patchSettings('gain', e.target.value === '' ? null : Math.max(0, parseInt(e.target.value, 10) || 0))}
                  className="w-24"
                />
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs text-slate-400 w-28">Max attempts</span>
                <Input
                  inputSize="sm" type="number" min={1} max={20} disabled={busy}
                  value={settings.max_attempts}
                  onChange={(e) => patchSettings('max_attempts', Math.min(20, Math.max(1, parseInt(e.target.value, 10) || 1)))}
                  className="w-16"
                />
              </div>
            </div>
          </SidebarSection>
        </div>

        <div className="border-l border-surface-border">
          <SidebarSection title="Live trials">
            {live && live.trials.length > 0 ? (
              <div className="flex flex-col gap-1 max-h-64 overflow-y-auto">
                {live.trials.slice().reverse().map((t, i) => (
                  <div key={i} className={`flex items-center gap-2 text-xs font-mono px-1.5 py-1 rounded ${t.saturated ? 'bg-rose-500/10 text-rose-300' : 'bg-surface-overlay text-slate-300'}`}>
                    <span className="w-16 truncate">{t.filterName ?? 'single'}</span>
                    <span className="text-slate-500">#{t.attempt}</span>
                    <span>{t.duration.toFixed(3)}s</span>
                    <span>{t.ratioPct.toFixed(1)}%</span>
                    {t.saturated && <span className="text-rose-400">saturated</span>}
                  </div>
                ))}
              </div>
            ) : (
              <span className="text-xs text-slate-600">No trials yet</span>
            )}
          </SidebarSection>

          <SidebarSection title="Results">
            {run && run.results.length > 0 ? (
              <div className="flex flex-col gap-2">
                {run.results.map((r, i) => (
                  <div key={i} className="flex items-start gap-2 text-xs">
                    <StatusPill variant={RESULT_PILL_VARIANT[r.status]} status={r.status} />
                    <div className="flex-1">
                      <div className="text-slate-300 font-mono">{r.filter_name ?? 'single pass'}</div>
                      {r.status === 'solved'
                        ? <div className="text-slate-500">{r.solved_duration?.toFixed(3)}s ({r.trials.length} trials)</div>
                        : <div className="text-rose-400">{r.error}</div>}
                    </div>
                  </div>
                ))}
                {run.task_id && (
                  <div className="text-xs text-emerald-400 mt-1">Queued on the sequencer (task {run.task_id.slice(0, 8)})</div>
                )}
                {run.status === 'failed' && !run.task_id && (
                  <div className="text-xs text-rose-400 mt-1">{run.error}</div>
                )}
              </div>
            ) : (
              <span className="text-xs text-slate-600">No results yet</span>
            )}
          </SidebarSection>
        </div>
      </div>
    </div>
  )
}
