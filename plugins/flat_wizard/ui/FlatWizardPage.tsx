import { useCallback, useEffect, useRef, useState } from 'react'
import { Sun, StopCircle } from 'lucide-react'
import { api } from '@/api/client'
import * as flatWizardApi from './api'
import { useStore } from '@/store'
import { Button } from '@/components/ui/button'
import { SidebarSection } from '@/components/ui/card'
import { DurationStepper } from '@/components/ui/duration-stepper'
import { CountStepper } from '@/components/ui/count-stepper'
import { Input } from '@/components/ui/input'
import { PillGroup } from '@/components/ui/pill-group'
import { StatusPill } from '@/components/ui/badge'
import type { StatusPillVariant } from '@/components/ui/badge'
import type {
  FilterWheelStatus,
  FlatFilterResult,
  FlatWizardCameraSpec,
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
  seed_duration: number
  max_duration: number
  max_attempts: number
}

const DEFAULT_SETTINGS: AdvancedSettings = {
  target_pct: 50,
  tolerance_pct: 5,
  saturation_pct: 95,
  binning: 1,
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

// Per-camera and per-combination UI state are keyed by device id / this key, so a
// camera or filter that disappears and comes back keeps the user's choices.
const comboKey = (cameraId: string, filterName: string | null) => `${cameraId}::${filterName ?? ''}`

interface CameraChoice {
  enabled: boolean
  manualWheelId: string   // only used when the camera has no optical path in the profile
  gain: number | null
}

interface ComboChoice {
  enabled: boolean
  count: number
}

interface CameraPlan {
  cameraId: string
  choice: CameraChoice
  hasOpticalPath: boolean
  wheelId: string | null             // the wheel actually used (null = single pass)
  wheelLabel: string                 // for display
  filterNames: (string | null)[]     // [null] = single pass
}

export function FlatWizardPage() {
  const connectedDevices = useStore((s) => s.connectedDevices)
  const live = useStore((s) => s.pluginStates['flat_wizard'] as FlatWizardLiveState | null | undefined)

  const cameras = connectedDevices.filter((d) => d.kind === 'camera')
  const filterWheels = connectedDevices.filter((d) => d.kind === 'filter_wheel')

  const [settings, setSettings] = useState<AdvancedSettings>(DEFAULT_SETTINGS)
  const [cameraChoices, setCameraChoices] = useState<Record<string, CameraChoice>>({})
  const [comboChoices, setComboChoices] = useState<Record<string, ComboChoice>>({})
  const [wheelStatuses, setWheelStatuses] = useState<Record<string, FilterWheelStatus | null>>({})

  const patchSettings = useCallback(<K extends keyof AdvancedSettings>(key: K, value: AdvancedSettings[K]) => {
    setSettings((s) => ({ ...s, [key]: value }))
  }, [])

  // Each camera's filter wheel comes from the active profile's equipment tree — same
  // approach as the autofocus/imaging pages, so a camera with no wheel on its optical
  // path never offers one just because some other camera on the rig has one.
  const [opticalPaths, setOpticalPaths] = useState<OpticalPath[]>([])
  useEffect(() => {
    api.profiles.activeOpticalPaths().then(setOpticalPaths).catch(() => setOpticalPaths([]))
  }, [])

  // Untouched cameras: enabled, gain pre-filled from the camera's equipment default.
  // Derived (not snapshotted) so it still applies when the optical paths load late.
  const defaultChoice = (cameraId: string): CameraChoice => ({
    enabled: true,
    manualWheelId: '',
    gain: opticalPaths.find((p) => p.camera_device_id === cameraId)?.camera.default_gain ?? null,
  })

  const plans: CameraPlan[] = cameras.map((cam) => {
    const choice = cameraChoices[cam.device_id] ?? defaultChoice(cam.device_id)
    const path = opticalPaths.find((p) => p.camera_device_id === cam.device_id) ?? null
    const pathWheel = path ? filterWheels.find((d) => d.device_id === path.filter_wheel_device_id) ?? null : null
    const wheelId = path ? (pathWheel?.device_id ?? null) : (choice.manualWheelId || null)
    const names = wheelId ? (wheelStatuses[wheelId]?.filter_names ?? []) : []
    return {
      cameraId: cam.device_id,
      choice,
      hasOpticalPath: path != null,
      // A wheel with no readable filter names can't be driven by name — single pass.
      wheelId: names.length ? wheelId : null,
      wheelLabel: wheelId ?? (path ? 'no filter wheel on its optical path' : 'no filter wheel'),
      filterNames: names.length ? names : [null],
    }
  })

  // Read every wheel in use (once each).
  const wheelIdsInUse = Array.from(new Set(cameras.flatMap((cam) => {
    const path = opticalPaths.find((p) => p.camera_device_id === cam.device_id)
    const id = path ? path.filter_wheel_device_id : cameraChoices[cam.device_id]?.manualWheelId
    return id ? [id] : []
  })))
  useEffect(() => {
    for (const id of wheelIdsInUse) {
      if (id in wheelStatuses) continue
      setWheelStatuses((s) => ({ ...s, [id]: null }))
      api.filterWheel.status(id)
        .then((st) => setWheelStatuses((s) => ({ ...s, [id]: st })))
        .catch(() => setWheelStatuses((s) => ({ ...s, [id]: null })))
    }
  }, [wheelIdsInUse.join('|')])  // eslint-disable-line react-hooks/exhaustive-deps

  const combo = (cameraId: string, filterName: string | null): ComboChoice =>
    comboChoices[comboKey(cameraId, filterName)] ?? { enabled: true, count: DEFAULT_COUNT }

  const patchCamera = (cameraId: string, patch: Partial<CameraChoice>) =>
    setCameraChoices((c) => ({
      ...c, [cameraId]: { ...(c[cameraId] ?? defaultChoice(cameraId)), ...patch },
    }))

  const patchCombo = (cameraId: string, filterName: string | null, patch: Partial<ComboChoice>) =>
    setComboChoices((c) => ({ ...c, [comboKey(cameraId, filterName)]: { ...combo(cameraId, filterName), ...patch } }))

  // A combination is shot when its camera and itself are ticked and it has frames.
  const cameraSpecs: FlatWizardCameraSpec[] = plans
    .filter((p) => p.choice.enabled)
    .map((p) => ({
      camera_id: p.cameraId,
      filter_wheel_id: p.wheelId,
      gain: p.choice.gain,
      filters: p.filterNames
        .map((name): FlatWizardFilterSpec => ({ filter_name: name, count: combo(p.cameraId, name).count }))
        .filter((f) => combo(p.cameraId, f.filter_name).enabled && f.count > 0),
    }))
    .filter((c) => c.filters.length > 0)
  const comboCount = cameraSpecs.reduce((n, c) => n + c.filters.length, 0)
  const frameCount = cameraSpecs.reduce((n, c) => n + c.filters.reduce((m, f) => m + f.count, 0), 0)

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

  const handleStart = useCallback(async () => {
    if (cameraSpecs.length === 0) { setError('Select at least one camera/filter combination with frames.'); return }
    setError(null)
    setBusy(true)
    setRun(null)

    const config: FlatWizardConfig = { cameras: cameraSpecs, ...settings }

    try {
      const r = await flatWizardApi.start(config)
      setRun(r)
      pollRef.current = setInterval(fetchRun, 1500)
    } catch (err) {
      setBusy(false)
      setError(err instanceof Error ? err.message : 'Failed to start the flat wizard')
    }
  }, [cameraSpecs, settings, fetchRun])

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
          <div className="flex items-center gap-3">
            <span className="text-xs text-slate-500">
              {cameraSpecs.length} camera{cameraSpecs.length === 1 ? '' : 's'} · {comboCount} set{comboCount === 1 ? '' : 's'} · {frameCount} frames
            </span>
            <Button size="sm" onClick={handleStart} disabled={comboCount === 0}>
              Solve &amp; Queue Flats
            </Button>
          </div>
        )}
      </div>

      {error && <div className="px-4 py-2 text-xs text-rose-400 bg-rose-500/10 border-b border-rose-500/20">{error}</div>}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-0 flex-1">
        <div>
          <SidebarSection title="Cameras & filters">
            {plans.length === 0 ? (
              <span className="text-xs text-slate-600">No camera connected</span>
            ) : (
              <div className="flex flex-col gap-4">
                {plans.map((p) => (
                  <div key={p.cameraId} className="flex flex-col gap-2">
                    <div className="flex items-center gap-2 flex-wrap">
                      <label className="flex items-center gap-2 cursor-pointer">
                        <input
                          type="checkbox" className="accent-accent" disabled={busy}
                          checked={p.choice.enabled}
                          onChange={(e) => patchCamera(p.cameraId, { enabled: e.target.checked })}
                        />
                        <span className="text-xs text-slate-200 font-mono">{p.cameraId}</span>
                      </label>
                      {p.hasOpticalPath || filterWheels.length === 0 ? (
                        <span className="text-xs text-slate-500">· {p.wheelLabel}</span>
                      ) : (
                        <select
                          value={p.choice.manualWheelId} disabled={busy || !p.choice.enabled}
                          onChange={(e) => patchCamera(p.cameraId, { manualWheelId: e.target.value })}
                          className="rounded bg-surface-overlay border border-surface-border px-1.5 py-0.5 text-xs text-slate-200 focus:outline-none focus:ring-1 focus:ring-accent">
                          <option value="">No filter wheel</option>
                          {filterWheels.map((d) => <option key={d.device_id} value={d.device_id}>{d.device_id}</option>)}
                        </select>
                      )}
                      <div className="flex items-center gap-1.5 ml-auto">
                        <span className="text-xs text-slate-400">Gain</span>
                        <Input
                          inputSize="sm" type="number" min={0} disabled={busy || !p.choice.enabled}
                          value={p.choice.gain ?? ''}
                          placeholder="driver default"
                          onChange={(e) => patchCamera(p.cameraId, {
                            gain: e.target.value === '' ? null : Math.max(0, parseInt(e.target.value, 10) || 0),
                          })}
                          className="w-24"
                        />
                      </div>
                    </div>
                    <div className={`flex flex-col gap-1.5 pl-5 ${p.choice.enabled ? '' : 'opacity-40'}`}>
                      {p.filterNames.map((name) => {
                        const c = combo(p.cameraId, name)
                        const off = busy || !p.choice.enabled
                        return (
                          <div key={name ?? ''} className="flex items-center gap-2">
                            <label className="flex items-center gap-2 w-24 cursor-pointer">
                              <input
                                type="checkbox" className="accent-accent" disabled={off}
                                checked={c.enabled}
                                onChange={(e) => patchCombo(p.cameraId, name, { enabled: e.target.checked })}
                              />
                              <span className="text-xs text-slate-300 font-mono truncate" title={name ?? 'no filter'}>
                                {name ?? 'no filter'}
                              </span>
                            </label>
                            <CountStepper
                              value={c.count} disabled={off || !c.enabled}
                              onChange={(v) => patchCombo(p.cameraId, name, { count: v })}
                            />
                            <span className="text-xs text-slate-500">frames</span>
                          </div>
                        )
                      })}
                    </div>
                  </div>
                ))}
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
                    <span className="w-28 truncate" title={t.cameraId}>
                      {plans.length > 1 ? `${t.cameraId} · ` : ''}{t.filterName ?? 'no filter'}
                    </span>
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
                      <div className="text-slate-300 font-mono">
                        {r.camera_id} · {r.filter_name ?? 'no filter'}
                      </div>
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
