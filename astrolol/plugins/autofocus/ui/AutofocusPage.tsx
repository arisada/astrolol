import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Contrast, Focus, StopCircle } from 'lucide-react'
import { api } from '@/api/client'
import * as autofocusApi from './api'
import { UCurveChart } from './AutofocusCurve'
import { useStore } from '@/store'
import { CollapsibleSidebar } from '@/components/ui/collapsible-sidebar'
import { Button } from '@/components/ui/button'
import { SidebarSection } from '@/components/ui/card'
import { CountStepper } from '@/components/ui/count-stepper'
import { DurationStepper } from '@/components/ui/duration-stepper'
import { FocuserRuler } from '@/components/ui/focuser-ruler'
import { Input } from '@/components/ui/input'
import { PillGroup } from '@/components/ui/pill-group'
import { StatusPill } from '@/components/ui/badge'
import { ToggleSwitch } from '@/components/ui/toggle-switch'
import type { StatusPillVariant } from '@/components/ui/badge'
import type {
  AutofocusConfig,
  AutofocusRun,
  AutofocusSettings,
  FilterWheelStatus,
  FitAlgo,
  FocusAction,
  FocusDataPoint,
  FocusMetric,
  OpticalPath,
} from '@/api/types'

// ── Autofocus exposure steps ──────────────────────────────────────────────────

const AUTOFOCUS_EXPOSURE_STEPS = [0.5, 1, 1.5, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 30]

const STEP_SIZE_PROGRESSION = [1, 2, 3, 5, 7, 10, 15, 20, 25, 30, 40, 50, 60, 75, 100, 125, 150, 200, 300, 500, 1000, 2000, 5000, 10000]

// ── Preview image panel ───────────────────────────────────────────────────────
// Star circles are burned into the JPEG server-side after detection,
// so no SVG overlay is needed here.

const RUN_PILL_VARIANT: Record<AutofocusRun['status'], StatusPillVariant> = {
  running: 'amber', completed: 'green', failed: 'red', aborted: 'slate',
}

// ── Default settings ──────────────────────────────────────────────────────────

const DEFAULT_SETTINGS: AutofocusSettings = {
  camera_id: null,
  step_size: 100,
  num_steps: 5,
  exposure_time: 2.0,
  binning: 1,
  gain: null,
  filter_slot: null,
  fit_algo: 'parabola',
  metric: 'hfd',
  lock_stars: false,
  on_edge: 'retry',
  on_flat: 'retry',
  on_noisy: 'retry',
  on_few_stars: 'retry',
  verify_after_move: false,
  on_mismatch: 'warn',
  max_retries: 2,
  retry_exposure_factor: 2,
  max_exposure: 16,
}

const FOCUS_ACTIONS: FocusAction[] = ['warn', 'retry', 'fail']
const DOUBT_CAUSES = ['edge', 'flat', 'noisy', 'few_stars'] as const
const MAX_RETRIES = [0, 1, 2, 3, 4, 5]
const EXPOSURE_FACTORS = [1.5, 2, 3, 4]

// ── Main page component ───────────────────────────────────────────────────────

/** Signed difference for display: +123, −45 or 0. */
function fmtDelta(d: number): string {
  return d > 0 ? `+${d}` : d < 0 ? `−${Math.abs(d)}` : '0'
}

export function AutofocusPage() {
  const { t } = useTranslation('autofocus')
  const connectedDevices = useStore((s) => s.connectedDevices)

  const cameras      = connectedDevices.filter((d) => d.kind === 'camera')
  const focusers     = connectedDevices.filter((d) => d.kind === 'focuser')
  const filterWheels = connectedDevices.filter((d) => d.kind === 'filter_wheel')

  // ── Configuration state ────────────────────────────────────────────────────
  const [cameraId,  setCameraId]  = useState<string>('')
  const [focuserId, setFocuserId] = useState<string>('')
  const [settings, setSettings]   = useState<AutofocusSettings>(DEFAULT_SETTINGS)
  const [settingsLoaded, setSettingsLoaded] = useState(false)
  const [filterWheelStatus, setFilterWheelStatus] = useState<FilterWheelStatus | null>(null)
  const settingsFetchedRef = useRef(false)
  // The camera is the user's own choice once they have picked one; until then the saved (or
  // first) camera is followed as devices connect.
  const cameraPickedRef = useRef(false)

  // Per-camera focuser/filter-wheel association resolved from the active profile's
  // equipment tree — same data Imaging.tsx uses to avoid cross-wiring devices between
  // cameras on different optical paths (e.g. a guide camera with no focuser must not
  // show the main camera's focuser, and vice versa).
  const [opticalPaths, setOpticalPaths] = useState<OpticalPath[]>([])
  useEffect(() => {
    api.profiles.activeOpticalPaths().then(setOpticalPaths).catch(() => setOpticalPaths([]))
  }, [])

  const opticalPath = cameraId ? (opticalPaths.find((p) => p.camera_device_id === cameraId) ?? null) : null

  // When the tree resolved this camera's optical path, trust it completely — including
  // "no focuser/filter wheel here" — instead of listing every connected device system-wide
  // regardless of which camera is selected. Only fall back to the full list when there's
  // no tree data for this camera (legacy profile, or the fetch hasn't landed yet).
  const resolvedFocuser = opticalPath
    ? focusers.find((d) => d.device_id === opticalPath.focuser_device_id) ?? null
    : null
  const focuserCandidates = opticalPath ? (resolvedFocuser ? [resolvedFocuser] : []) : focusers

  const resolvedFilterWheel = opticalPath
    ? filterWheels.find((d) => d.device_id === opticalPath.filter_wheel_device_id) ?? null
    : null
  const filterWheelCandidates = opticalPath ? (resolvedFilterWheel ? [resolvedFilterWheel] : []) : filterWheels

  // ── Saving ─────────────────────────────────────────────────────────────────
  // The settings are what the sequencer runs its autofocus with, so every change is saved
  // (shortly after the last one), not only the ones made before pressing Start.
  const [error, setError] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  const settingsRef = useRef(settings)
  const dirtyRef = useRef(false)
  useEffect(() => { settingsRef.current = settings }, [settings])

  const flushSettings = useCallback(() => {
    if (!dirtyRef.current) return
    dirtyRef.current = false
    autofocusApi.putSettings(settingsRef.current)
      .then(() => setSaveError(null))
      .catch(() => { dirtyRef.current = true; setSaveError(t('saveFailed')) })
  }, [t])

  useEffect(() => {
    if (!dirtyRef.current) return
    const id = setTimeout(flushSettings, 500)
    return () => clearTimeout(id)
  }, [settings, flushSettings])

  // Leaving the page within that half second must not lose the last change.
  useEffect(() => flushSettings, [flushSettings])

  // Helper to patch a single settings key
  const patchSettings = useCallback(<K extends keyof AutofocusSettings>(key: K, value: AutofocusSettings[K]) => {
    dirtyRef.current = true
    setSettings((s) => ({ ...s, [key]: value }))
  }, [])

  const pickCamera = useCallback((id: string) => {
    cameraPickedRef.current = true
    setCameraId(id)
    patchSettings('camera_id', id)
  }, [patchSettings])

  // ── Run state ──────────────────────────────────────────────────────────────
  const [run, setRun]   = useState<AutofocusRun | null>(null)
  const [busy, setBusy] = useState(false)

  const [previewStep, setPreviewStep] = useState<number | null>(null)
  const [previewKey,  setPreviewKey]  = useState(0)
  const [stretchMode, setStretchMode] = useState<'auto' | 'linear'>('auto')

  // Manual starting position — empty string means "use the focuser's current position".
  const [startPositionRaw, setStartPositionRaw] = useState('')
  const focuserStatuses = useStore((s) => s.focuserStatuses)
  const focuserPosition = focuserId ? focuserStatuses[focuserId]?.position ?? null : null

  // ── Load persisted settings on mount ──────────────────────────────────────
  useEffect(() => {
    if (settingsFetchedRef.current) return
    settingsFetchedRef.current = true
    autofocusApi.getSettings()
      .then((s) => { if (!dirtyRef.current) setSettings(s) })   // a change made meanwhile wins
      .catch(() => {/* use defaults */})
      .finally(() => setSettingsLoaded(true))
  }, [])

  // The camera used last time, else the first one. Devices may connect after the page opens,
  // so keep following that choice until the user picks a camera themselves.
  useEffect(() => {
    if (!settingsLoaded || cameras.length === 0) return
    const preferred = cameras.find((d) => d.device_id === settings.camera_id) ?? cameras[0]
    const stillThere = cameras.some((d) => d.device_id === cameraId)
    if (!cameraId || !stillThere || (!cameraPickedRef.current && cameraId !== preferred.device_id)) {
      setCameraId(preferred.device_id)
    }
  }, [cameras, settingsLoaded, settings.camera_id])  // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (opticalPath) {
      // Tree is authoritative for this camera: switch (or clear) even if the user had
      // manually picked a focuser before switching cameras.
      setFocuserId(opticalPath.focuser_device_id ?? '')
    } else if (!focuserId && focusers.length > 0) {
      setFocuserId(focusers[0].device_id)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cameraId, opticalPaths, focusers])

  useEffect(() => {
    if (!resolvedFilterWheel) { setFilterWheelStatus(null); return }
    api.filterWheel.status(resolvedFilterWheel.device_id)
      .then(setFilterWheelStatus)
      .catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cameraId, opticalPaths, filterWheels])

  // ── Polling ────────────────────────────────────────────────────────────────
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const fetchRun = useCallback(async () => {
    try {
      const r = await autofocusApi.run()
      setRun(r)
      if (r.status !== 'running') {
        setBusy(false)
        setPreviewKey((k) => k + 1)
        if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
      } else {
        setPreviewKey((k) => k + 1)
      }
    } catch { /* 404 = no run yet */ }
  }, [])

  // Restore state on mount if a run is already active
  useEffect(() => {
    autofocusApi.run().then((r) => {
      setRun(r)
      if (r.status === 'running') {
        setBusy(true)
        pollRef.current = setInterval(fetchRun, 1500)
      }
    }).catch(() => {})
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [fetchRun])

  // ── Actions ────────────────────────────────────────────────────────────────
  const handleStart = useCallback(async () => {
    if (!cameraId || !focuserId) { setError(t('needDevices')); return }
    setError(null)
    setBusy(true)
    setRun(null)
    setPreviewStep(null)

    flushSettings()

    const { camera_id: _savedCamera, ...runSettings } = settings
    const config: AutofocusConfig = {
      camera_id: cameraId,
      focuser_id: focuserId,
      filter_wheel_id: resolvedFilterWheel?.device_id ?? null,
      start_position: startPositionRaw ? parseInt(startPositionRaw, 10) : null,
      ...runSettings,
    }

    try {
      const r = await autofocusApi.start(config)
      setRun(r)
      pollRef.current = setInterval(fetchRun, 1500)
    } catch (err) {
      setBusy(false)
      setError(err instanceof Error ? err.message : t('startFailed'))
    }
  }, [cameraId, focuserId, resolvedFilterWheel, settings, startPositionRaw, fetchRun, flushSettings, t])

  const handleAbort = useCallback(async () => {
    try { await autofocusApi.abort(); await fetchRun() }
    catch { setBusy(false) }
  }, [fetchRun])

  // ── Derived display values ─────────────────────────────────────────────────
  // Use the last *completed* data point — run.current_step is set at the
  // start of each iteration before exposure/preview are ready.
  const lastDp      = run?.data_points.length ? run.data_points[run.data_points.length - 1] : null
  const displayStep = previewStep ?? lastDp?.step ?? null
  const previewUrl  = displayStep ? `${autofocusApi.previewUrl(displayStep, stretchMode)}&k=${previewKey}` : null

  const bestDataPoint = run?.data_points.filter((d) => d.fwhm > 0).reduce(
    (best, dp) => (!best || dp.fwhm < best.fwhm ? dp : best), null as FocusDataPoint | null,
  )

  const BINNINGS = [1, 2, 3, 4]

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className="flex h-full overflow-hidden bg-surface-bg">

      {/* ── Left: image preview ── */}
      <div className="flex-1 flex flex-col items-center justify-center bg-black min-w-0 relative">
        {previewUrl && (
          <Button
            size="sm" variant="outline"
            onClick={() => setStretchMode((m) => (m === 'auto' ? 'linear' : 'auto'))}
            title={t('stretchTitle')}
            className="absolute top-2 right-2 z-10 bg-black/60 backdrop-blur-sm"
          >
            <Contrast size={13} className="mr-1.5" />
            {stretchMode === 'auto' ? t('autoStretch') : t('linear')}
          </Button>
        )}
        {previewUrl ? (
          <img src={previewUrl} alt={t('focusStep')} className="max-w-full max-h-full object-contain" />
        ) : (
          <div className="flex flex-col items-center gap-3 text-slate-600">
            <Focus size={48} strokeWidth={1} />
            <p className="text-sm">{t('startHint')}</p>
          </div>
        )}

        {/* Step selector thumbnails */}
        {run && run.data_points.length > 1 && (
          <div className="absolute bottom-0 left-0 right-0 flex gap-1 px-3 py-2 bg-gradient-to-t from-black/80 overflow-x-auto">
            {run.data_points.map((dp) => (
              <button
                key={dp.step}
                onClick={() => setPreviewStep(dp.step)}
                title={t('stepTitle', { step: dp.step, position: dp.position, metric: (run.config.metric ?? 'fwhm').toUpperCase(), value: dp.fwhm.toFixed(2) })}
                className={`flex-none text-[10px] px-1.5 py-0.5 rounded transition-colors ${
                  (previewStep ?? run.current_step) === dp.step
                    ? 'bg-accent text-accent-fg'
                    : 'bg-white/10 text-slate-300 hover:bg-white/20'
                }`}
              >
                {dp.position}
                {dp.fwhm > 0 && (
                  <span className={`ml-1 ${dp === bestDataPoint ? 'text-green-400 font-bold' : 'text-slate-400'}`}>
                    {dp.fwhm.toFixed(1)}
                  </span>
                )}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* ── Right: sidebar ── */}
      <CollapsibleSidebar>

        {/* Camera */}
        <SidebarSection title={t('camera.title')} foldId="autofocus.camera">
          {cameras.length === 0 ? (
            <span className="text-xs text-slate-600">{t('camera.none')}</span>
          ) : cameras.length === 1 ? (
            <span className="text-xs text-slate-300 font-mono">{cameras[0].device_id}</span>
          ) : (
            <select value={cameraId} onChange={(e) => pickCamera(e.target.value)}
              className="w-full rounded-lg bg-surface border border-surface-border px-2 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent">
              {cameras.map((d) => <option key={d.device_id} value={d.device_id}>{d.device_id}</option>)}
            </select>
          )}
        </SidebarSection>

        {/* Focuser */}
        <SidebarSection title={t('focuser.title')} foldId="autofocus.focuser">
          {focuserCandidates.length === 0 ? (
            <span className="text-xs text-slate-600">{t('focuser.none')}</span>
          ) : focuserCandidates.length === 1 ? (
            <span className="text-xs text-slate-300 font-mono">{focuserCandidates[0].device_id}</span>
          ) : (
            <select value={focuserId} onChange={(e) => setFocuserId(e.target.value)}
              className="w-full rounded-lg bg-surface border border-surface-border px-2 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent">
              {focuserCandidates.map((d) => <option key={d.device_id} value={d.device_id}>{d.device_id}</option>)}
            </select>
          )}
        </SidebarSection>

        {/* V-curve configuration */}
        <SidebarSection title={t('vcurve.title')} foldId="autofocus.vcurve">
          <div className="flex flex-col gap-3">

            {/* Metric selector */}
            <PillGroup
              options={['fwhm', 'hfd'] as FocusMetric[]}
              value={settings.metric}
              onChange={(m) => patchSettings('metric', m)}
              label={t('vcurve.metric')}
              formatLabel={(m) => m.toUpperCase()}
              stretch
            />

            {/* Algorithm selector */}
            <PillGroup
              options={['parabola', 'hyperbola'] as FitAlgo[]}
              value={settings.fit_algo}
              onChange={(a) => patchSettings('fit_algo', a)}
              label={t('vcurve.algo')}
              formatLabel={(a) => t(`vcurve.${a}`)}
              stretch
            />

            {/* Step size */}
            <CountStepper
              label={`${t('vcurve.stepSize')} (${t('vcurve.steps')})`}
              value={settings.step_size}
              onChange={(v) => patchSettings('step_size', Math.max(1, v))}
              steps={STEP_SIZE_PROGRESSION}
              min={1}
            />

            {/* Steps each side */}
            <div className="flex flex-col gap-1">
              <label className="text-xs text-slate-400">
                {t('vcurve.eachSide')}<span className="text-slate-300">{t('vcurve.total', { count: settings.num_steps * 2 + 1 })}</span>
              </label>
              <div className="flex items-center gap-2">
                <input
                  type="range" min={3} max={15} value={settings.num_steps}
                  onChange={(e) => patchSettings('num_steps', parseInt(e.target.value, 10))}
                  className="range-thin flex-1"
                  style={{ ['--v' as string]: `${((settings.num_steps - 3) / 12) * 100}%` }}
                />
                <span className="text-xs text-slate-300 w-4 text-center">{settings.num_steps}</span>
              </div>
            </div>

            {/* Manual starting position */}
            <div className="flex flex-col gap-1">
              <label className="text-xs text-slate-400">
                {t('vcurve.startPos')} <span className="text-slate-600">{t('vcurve.optional')}</span>
              </label>
              <div className="flex items-center gap-1">
                <Input
                  inputSize="sm"
                  type="text" inputMode="numeric"
                  placeholder={focuserPosition !== null ? t('vcurve.currentPos', { position: focuserPosition }) : t('vcurve.currentPosPlaceholder')}
                  value={startPositionRaw}
                  onChange={(e) => setStartPositionRaw(e.target.value.replace(/[^0-9]/g, ''))}
                  className="flex-1"
                />
                {startPositionRaw && (
                  <Button size="icon" variant="outline" onClick={() => setStartPositionRaw('')} title={t('vcurve.useCurrent')}>
                    ×
                  </Button>
                )}
              </div>
            </div>

            {/* Lock onto the same stars for every step */}
            <div className="flex items-center justify-between gap-2 pt-1">
              <label className="text-xs text-slate-400 leading-tight">
                {t('vcurve.track')}
                <span className="block text-[10px] text-slate-600">
                  {t('vcurve.trackHint')}
                </span>
              </label>
              <ToggleSwitch
                label={t('vcurve.trackLabel')}
                checked={settings.lock_stars}
                onChange={() => patchSettings('lock_stars', !settings.lock_stars)}
              />
            </div>
          </div>
        </SidebarSection>

        {/* Exposure */}
        <SidebarSection title={t('exposure.title')} foldId="autofocus.exposure">
          <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-1">
              <label className="text-xs text-slate-400">{t('exposure.duration')}</label>
              <DurationStepper steps={AUTOFOCUS_EXPOSURE_STEPS} value={settings.exposure_time} onChange={(v) => patchSettings('exposure_time', v)} />
            </div>

            <PillGroup
              options={BINNINGS}
              value={settings.binning}
              onChange={(b) => patchSettings('binning', b)}
              label={t('exposure.binning')}
              formatLabel={(b) => `${b}×${b}`}
            />

            <div className="flex flex-col gap-1">
              <label className="text-xs text-slate-400">{t('exposure.gain')} <span className="text-slate-600">{t('vcurve.optional')}</span></label>
              <Input
                inputSize="sm"
                type="number" min={0}
                placeholder={t('exposure.gainPlaceholder')}
                value={settings.gain ?? ''}
                onChange={(e) => patchSettings('gain', e.target.value ? parseInt(e.target.value, 10) : null)}
              />
            </div>

            {filterWheelCandidates.length > 0 && (
              <div className="flex flex-col gap-1">
                <label className="text-xs text-slate-400">{t('exposure.filter')} <span className="text-slate-600">{t('vcurve.optional')}</span></label>
                <select
                  value={settings.filter_slot ?? ''}
                  onChange={(e) => patchSettings('filter_slot', e.target.value ? parseInt(e.target.value, 10) : null)}
                  className="w-full rounded-lg bg-surface border border-surface-border px-2 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent"
                >
                  <option value="">{t('exposure.keep')}</option>
                  {filterWheelStatus?.filter_names.length
                    ? filterWheelStatus.filter_names.map((name, i) => (
                        <option key={i + 1} value={i + 1}>{name}</option>
                      ))
                    : Array.from({ length: filterWheelStatus?.filter_count ?? 5 }, (_, i) => (
                        <option key={i + 1} value={i + 1}>{t('exposure.slot', { n: i + 1 })}</option>
                      ))
                  }
                </select>
              </div>
            )}
          </div>
        </SidebarSection>

        {/* A doubtful result */}
        <SidebarSection title={t('doubt.title')} foldId="autofocus.doubt">
          <div className="flex flex-col gap-3">
            <p className="text-[10px] text-slate-600">{t('doubt.hint')}</p>
            {DOUBT_CAUSES.map((cause) => {
              const key = `on_${cause}` as const
              return (
                <PillGroup
                  key={cause}
                  options={FOCUS_ACTIONS}
                  value={settings[key]}
                  onChange={(a) => patchSettings(key, a)}
                  label={t(`doubt.cause.${cause}`)}
                  formatLabel={(a) => t(`doubt.action.${a}`)}
                />
              )
            })}
            <div className="flex items-center justify-between gap-2">
              <label className="text-xs text-slate-400 leading-tight">
                {t('doubt.verify')}
                <span className="block text-[10px] text-slate-600">{t('doubt.verifyHint')}</span>
              </label>
              <ToggleSwitch
                label={t('doubt.verify')}
                checked={settings.verify_after_move}
                onChange={() => patchSettings('verify_after_move', !settings.verify_after_move)}
              />
            </div>
            {settings.verify_after_move && (
              <PillGroup
                options={FOCUS_ACTIONS}
                value={settings.on_mismatch}
                onChange={(a) => patchSettings('on_mismatch', a)}
                label={t('doubt.cause.mismatch')}
                formatLabel={(a) => t(`doubt.action.${a}`)}
              />
            )}
            <PillGroup
              options={MAX_RETRIES}
              value={settings.max_retries}
              onChange={(n) => patchSettings('max_retries', n)}
              label={t('doubt.maxRetries')}
            />
            {settings.max_retries > 0 && (
              <>
                <PillGroup
                  options={EXPOSURE_FACTORS}
                  value={settings.retry_exposure_factor}
                  onChange={(f) => patchSettings('retry_exposure_factor', f)}
                  label={t('doubt.factor')}
                  formatLabel={(f) => `×${f}`}
                />
                <div className="flex flex-col gap-1">
                  <label className="text-xs text-slate-400">{t('doubt.maxExposure')}</label>
                  <DurationStepper
                    steps={AUTOFOCUS_EXPOSURE_STEPS}
                    value={settings.max_exposure}
                    onChange={(v) => patchSettings('max_exposure', v)}
                  />
                </div>
              </>
            )}
          </div>
        </SidebarSection>

        {/* Action */}
        <div className="px-4 py-3 border-b border-surface-border flex flex-col gap-2">
          {error && <p className="text-xs text-red-400">{error}</p>}
          {saveError && <p className="text-xs text-red-400">{saveError}</p>}
          <Button
            onClick={handleStart}
            disabled={busy || cameras.length === 0 || focuserCandidates.length === 0}
            className="w-full"
          >
            <Focus size={13} className="mr-2" />
            {busy ? t('running') : t('start')}
          </Button>
          {busy && (
            <Button variant="danger" onClick={handleAbort} className="w-full">
              <StopCircle size={13} className="mr-2" />
              {t('abort')}
            </Button>
          )}
        </div>

        {/* Progress */}
        {run && (
          <SidebarSection title={t('progress.title')}>
            <div className="flex flex-col gap-2">
              <div className="flex items-center justify-between">
                <span className="text-xs text-slate-300">
                  {run.status === 'running'
                    ? t('progress.step', { current: run.current_step, total: run.total_steps })
                    : t('progress.steps', { total: run.total_steps })}
                </span>
                <StatusPill status={t(`status.${run.status}`)} variant={RUN_PILL_VARIANT[run.status]} pulse={run.status === 'running'} />
              </div>

              {run.total_steps > 0 && (
                <div className="h-[3px] bg-surface-overlay rounded overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all duration-500 ${
                      run.status === 'completed' ? 'bg-green-500' :
                      run.status === 'failed'    ? 'bg-red-500'   :
                      run.status === 'aborted'   ? 'bg-slate-500' : 'bg-accent'
                    }`}
                    style={{ width: `${(run.current_step / run.total_steps) * 100}%` }}
                  />
                </div>
              )}

              {run.data_points.length > 0 && (() => {
                const latest = run.data_points[run.data_points.length - 1]
                const metricLabel = (run.config.metric ?? 'fwhm').toUpperCase()
                return (
                  <div className="text-xs text-slate-400 space-y-0.5">
                    <div>{t('progress.position')} <span className="text-slate-200 font-mono">{latest.position}</span></div>
                    <div>
                      {metricLabel}:{' '}
                      <span className={`font-mono ${latest === bestDataPoint ? 'text-green-400' : 'text-slate-200'}`}>
                        {latest.fwhm > 0 ? `${latest.fwhm.toFixed(2)} px` : '—'}
                      </span>
                    </div>
                    <div>{t('progress.stars')} <span className="text-slate-200 font-mono">{latest.star_count}</span></div>
                  </div>
                )
              })()}

              {run.attempts.length > 0 && run.exposure_time != null && (
                <p className="text-xs text-amber-400">
                  {t('progress.retry', { count: run.attempts.length, exposure: run.exposure_time })}
                </p>
              )}

              {run.error && <p className="text-xs text-red-400 break-words">{run.error}</p>}
            </div>
          </SidebarSection>
        )}

        {/* Focuser position: where we are, where we are going, and where the run started */}
        {run && (() => {
          const positions = run.data_points.map((d) => d.position)
          const reach = (run.config.num_steps ?? 0) * (run.config.step_size ?? 0)
          const here = focuserPosition ?? positions[positions.length - 1] ?? run.initial_position
          const known = [run.initial_position, run.optimal_position, here, ...positions].filter((v): v is number => v != null)
          if (known.length === 0 || here == null) return null
          const centre = run.config.start_position ?? run.initial_position ?? here
          const lo = Math.min(...known, centre - reach)
          const hi = Math.max(...known, centre + reach)
          const pad = Math.max(10, (hi - lo) * 0.08)
          return (
            <SidebarSection title={t('ruler.title')}>
              <FocuserRuler
                position={here}
                target={run.optimal_position}
                initial={run.initial_position}
                min={Math.max(0, Math.floor(lo - pad))}
                max={Math.ceil(hi + pad)}
                label={t('ruler.title')}
                legend={{
                  position: t('ruler.position', { value: here }),
                  target: run.optimal_position != null ? t('ruler.optimal', { value: run.optimal_position }) : undefined,
                  initial: run.initial_position != null ? t('ruler.initial', { value: run.initial_position }) : undefined,
                }}
              />
            </SidebarSection>
          )
        })()}

        {/* V-curve chart */}
        {run && run.data_points.length > 0 && (
          <SidebarSection title={t('vcurve.title')}>
            <UCurveChart
              dataPoints={run.data_points}
              previous={run.attempts.flatMap((a) => a.data_points)}
              curveFit={run.curve_fit}
              optimal={run.optimal_position}
              fitAlgo={run.config.fit_algo ?? 'parabola'}
              metric={run.config.metric ?? 'fwhm'}
            />
          </SidebarSection>
        )}

        {/* Result */}
        {run?.status === 'completed' && run.optimal_position !== null && (
          <SidebarSection title={t('result.title')}>
            <div className="flex flex-col gap-1.5">
              <div className="flex items-baseline gap-2">
                <span className="text-xs text-slate-400">{t('result.optimal')}</span>
                <span className="text-lg font-mono text-green-400">{run.optimal_position}</span>
                {run.initial_position != null && (
                  <span className="text-sm font-mono text-slate-400" title={t('result.fromStartTitle', { position: run.initial_position })}>
                    {`(${fmtDelta(run.optimal_position - run.initial_position)})`}
                  </span>
                )}
              </div>
              {run.quality && (
                <div className="flex flex-col gap-0.5">
                  <StatusPill
                    variant={run.quality.verdict === 'good' ? 'green' : 'amber'}
                    status={t(`quality.${run.quality.verdict}`)}
                  />
                  {run.quality.causes.map((cause) => (
                    <p key={cause} className="text-xs text-amber-400">{t(`quality.cause.${cause}`)}</p>
                  ))}
                </div>
              )}
              {bestDataPoint && (
                <div className="text-xs text-slate-500">
                  {t('result.best', { metric: (run.config.metric ?? 'fwhm').toUpperCase() })} <span className="text-slate-300 font-mono">{bestDataPoint.fwhm.toFixed(2)} px</span>
                  {' '}{t('result.at', { position: bestDataPoint.position })}
                </div>
              )}
            </div>
          </SidebarSection>
        )}

      </CollapsibleSidebar>
    </div>
  )
}
