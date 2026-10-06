import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronDown, ChevronUp, Contrast, Focus, StopCircle } from 'lucide-react'
import { api } from '@/api/client'
import * as autofocusApi from './api'
import { useStore } from '@/store'
import { CollapsibleSidebar } from '@/components/ui/collapsible-sidebar'
import { Button } from '@/components/ui/button'
import { SidebarSection } from '@/components/ui/card'
import { DurationStepper } from '@/components/ui/duration-stepper'
import { Input } from '@/components/ui/input'
import { PillGroup } from '@/components/ui/pill-group'
import { StatusPill } from '@/components/ui/badge'
import { ToggleSwitch } from '@/components/ui/toggle-switch'
import type { StatusPillVariant } from '@/components/ui/badge'
import type {
  AutofocusConfig,
  AutofocusRun,
  AutofocusSettings,
  CurveFit,
  FilterWheelStatus,
  FitAlgo,
  FocusDataPoint,
  FocusMetric,
  OpticalPath,
} from '@/api/types'

// ── Autofocus exposure steps ──────────────────────────────────────────────────

const AUTOFOCUS_EXPOSURE_STEPS = [0.5, 1, 1.5, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 30]

const STEP_SIZE_PROGRESSION = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000]

// ── Integer field with progression up/down buttons ────────────────────────────
// Plain <input type=number> can't be cleared to retype a leading digit (parseInt('')
// falls back to the min and instantly repopulates the field), and its native
// spinner only ever does +/-1. This keeps a local editable string that commits on
// blur/Enter, and steps through `progression` instead of +/-1.

function IntegerStepper({
  label, unit, value, onChange, progression, min = 0,
}: {
  label: string
  unit?: string
  value: number
  onChange: (v: number) => void
  progression: number[]
  min?: number
}) {
  const { t } = useTranslation('autofocus')
  const [raw, setRaw] = useState(String(value))
  const editingRef = useRef(false)

  useEffect(() => {
    if (!editingRef.current) setRaw(String(value))
  }, [value])

  const commit = () => {
    editingRef.current = false
    const n = parseInt(raw, 10)
    if (!isNaN(n)) onChange(Math.max(min, n))
    else setRaw(String(value))
  }

  const stepDown = () => {
    const lower = progression.filter((v) => v < value)
    onChange(lower.length ? lower[lower.length - 1] : progression[0])
  }
  const stepUp = () => {
    const higher = progression.filter((v) => v > value)
    onChange(higher.length ? higher[0] : progression[progression.length - 1])
  }

  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs text-slate-400">{label}</label>
      <div className="flex items-center gap-1">
        <Button size="icon" variant="outline" onClick={stepDown} title={t('decrease')}>
          <ChevronDown size={14} />
        </Button>
        <input
          type="text" inputMode="numeric" value={raw}
          onFocus={() => { editingRef.current = true }}
          onChange={(e) => { editingRef.current = true; setRaw(e.target.value.replace(/[^0-9]/g, '')) }}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === 'Enter') (e.target as HTMLInputElement).blur()
            if (e.key === 'Escape') { setRaw(String(value)); editingRef.current = false; (e.target as HTMLInputElement).blur() }
          }}
          className="flex-1 min-w-0 text-center text-xs font-mono text-slate-200 bg-surface-overlay border border-surface-border rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-accent"
        />
        <Button size="icon" variant="outline" onClick={stepUp} title={t('increase')}>
          <ChevronUp size={14} />
        </Button>
        {unit && <span className="text-xs text-slate-500">{unit}</span>}
      </div>
    </div>
  )
}

// ── U-curve SVG chart ─────────────────────────────────────────────────────────

function UCurveChart({
  dataPoints,
  curveFit,
  optimal,
  fitAlgo,
  metric,
}: {
  dataPoints: FocusDataPoint[]
  curveFit: CurveFit | null
  optimal: number | null
  fitAlgo: FitAlgo
  metric: FocusMetric
}) {
  const { t } = useTranslation('autofocus')
  const W = 260, H = 150
  const pad = { t: 8, r: 10, b: 24, l: 34 }
  const cw = W - pad.l - pad.r
  const ch = H - pad.t - pad.b

  if (dataPoints.length === 0) {
    return (
      <div className="flex items-center justify-center h-[150px] text-xs text-slate-600">
        {t('noData')}
      </div>
    )
  }

  const positions = dataPoints.map((d) => d.position)
  const fwhms = dataPoints.filter((d) => d.fwhm > 0).map((d) => d.fwhm)
  if (fwhms.length === 0) return null

  const minX = Math.min(...positions)
  const maxX = Math.max(...positions)
  const maxY = Math.max(...fwhms) * 1.2
  const rangeX = maxX - minX || 1

  const toX = (pos: number) => pad.l + ((pos - minX) / rangeX) * cw
  const toY = (fwhm: number) => pad.t + (1 - fwhm / maxY) * ch

  // Fitted curve — sampled at 80 points across the range
  let curvePath = ''
  if (curveFit) {
    const { a, b, c } = curveFit
    const pts = Array.from({ length: 80 }, (_, i) => {
      const x = minX + (i / 79) * rangeX
      const y = fitAlgo === 'hyperbola'
        ? Math.sqrt(Math.max(0, a * x * x + b * x + c))
        : a * x * x + b * x + c
      if (y < 0 || y > maxY * 1.1) return null
      return `${toX(x).toFixed(1)},${toY(y).toFixed(1)}`
    }).filter(Boolean)
    if (pts.length >= 2) curvePath = `M ${pts.join(' L ')}`
  }

  const showOptimal =
    optimal !== null && optimal >= minX - rangeX * 0.05 && optimal <= maxX + rangeX * 0.05

  const yLabels = [maxY, maxY / 2, 0]

  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} className="block">
      <rect x={pad.l} y={pad.t} width={cw} height={ch} fill="#0f1623" stroke="#1e293b" strokeWidth={0.5} />

      {yLabels.map((fwhm, i) => (
        <g key={i}>
          <line x1={pad.l} y1={toY(fwhm)} x2={pad.l + cw} y2={toY(fwhm)} stroke="#1e293b" strokeWidth={0.5} />
          <text x={pad.l - 3} y={toY(fwhm) + 3} textAnchor="end" fill="#475569" fontSize={7}>
            {fwhm === 0 ? '0' : fwhm.toFixed(1)}
          </text>
        </g>
      ))}

      <text x={7} y={pad.t + ch / 2} textAnchor="middle" fill="#475569" fontSize={7}
        transform={`rotate(-90 7 ${pad.t + ch / 2})`}>{metric === 'hfd' ? t('hfdAxis') : t('fwhmAxis')}</text>

      {Array.from({ length: Math.min(5, positions.length) }, (_, i) => {
        const pos = rangeX === 0
          ? minX
          : Math.round(minX + (i / (Math.min(5, positions.length) - 1 || 1)) * rangeX)
        return (
          <g key={i}>
            <line x1={toX(pos)} y1={pad.t + ch} x2={toX(pos)} y2={pad.t + ch + 3} stroke="#334155" strokeWidth={0.5} />
            <text x={toX(pos)} y={H - 4} textAnchor="middle" fill="#475569" fontSize={6.5}>{pos}</text>
          </g>
        )
      })}

      {curvePath && (
        <path d={curvePath} stroke="#f87171" fill="none" strokeWidth={1.5} strokeLinejoin="round" />
      )}

      {showOptimal && (
        <line x1={toX(optimal!)} y1={pad.t} x2={toX(optimal!)} y2={pad.t + ch}
          stroke="#4ade80" strokeWidth={1} strokeDasharray="3,2" />
      )}

      {dataPoints.filter((dp) => dp.fwhm > 0).map((dp, i) => (
        <circle key={i} cx={toX(dp.position)} cy={toY(dp.fwhm)}
          r={3} fill="#60a5fa" stroke="#1d4ed8" strokeWidth={0.5} />
      ))}
    </svg>
  )
}

// ── Preview image panel ───────────────────────────────────────────────────────
// Star circles are burned into the JPEG server-side after detection,
// so no SVG overlay is needed here.

const RUN_PILL_VARIANT: Record<AutofocusRun['status'], StatusPillVariant> = {
  running: 'amber', completed: 'green', failed: 'red', aborted: 'slate',
}

// ── Default settings ──────────────────────────────────────────────────────────

const DEFAULT_SETTINGS: AutofocusSettings = {
  step_size: 100,
  num_steps: 5,
  exposure_time: 2.0,
  binning: 1,
  gain: null,
  filter_slot: null,
  fit_algo: 'parabola',
  metric: 'fwhm',
  lock_stars: false,
}

// ── Main page component ───────────────────────────────────────────────────────

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
  const [filterWheelStatus, setFilterWheelStatus] = useState<FilterWheelStatus | null>(null)
  const settingsLoadedRef = useRef(false)

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

  // Helper to patch a single settings key
  const patchSettings = useCallback(<K extends keyof AutofocusSettings>(key: K, value: AutofocusSettings[K]) => {
    setSettings((s) => ({ ...s, [key]: value }))
  }, [])

  // ── Run state ──────────────────────────────────────────────────────────────
  const [run, setRun]   = useState<AutofocusRun | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [previewStep, setPreviewStep] = useState<number | null>(null)
  const [previewKey,  setPreviewKey]  = useState(0)
  const [stretchMode, setStretchMode] = useState<'auto' | 'linear'>('auto')

  // Manual starting position — empty string means "use the focuser's current position".
  const [startPositionRaw, setStartPositionRaw] = useState('')
  const focuserStatuses = useStore((s) => s.focuserStatuses)
  const focuserPosition = focuserId ? focuserStatuses[focuserId]?.position ?? null : null

  // ── Load persisted settings on mount ──────────────────────────────────────
  useEffect(() => {
    if (settingsLoadedRef.current) return
    settingsLoadedRef.current = true
    autofocusApi.getSettings()
      .then((s) => setSettings(s))
      .catch(() => {/* use defaults */})
  }, [])

  // Auto-select first available device when devices change
  useEffect(() => {
    if (!cameraId && cameras.length > 0) setCameraId(cameras[0].device_id)
  }, [cameras])  // eslint-disable-line react-hooks/exhaustive-deps

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

    // Persist settings before starting
    autofocusApi.putSettings(settings).catch(() => {})

    const config: AutofocusConfig = {
      camera_id: cameraId,
      focuser_id: focuserId,
      filter_wheel_id: resolvedFilterWheel?.device_id ?? null,
      start_position: startPositionRaw ? parseInt(startPositionRaw, 10) : null,
      ...settings,
    }

    try {
      const r = await autofocusApi.start(config)
      setRun(r)
      pollRef.current = setInterval(fetchRun, 1500)
    } catch (err) {
      setBusy(false)
      setError(err instanceof Error ? err.message : t('startFailed'))
    }
  }, [cameraId, focuserId, resolvedFilterWheel, settings, startPositionRaw, fetchRun, t])

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
                    ? 'bg-accent text-white'
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
        <SidebarSection title={t('camera.title')}>
          {cameras.length === 0 ? (
            <span className="text-xs text-slate-600">{t('camera.none')}</span>
          ) : cameras.length === 1 ? (
            <span className="text-xs text-slate-300 font-mono">{cameras[0].device_id}</span>
          ) : (
            <select value={cameraId} onChange={(e) => setCameraId(e.target.value)}
              className="w-full rounded bg-surface-overlay border border-surface-border px-2 py-1.5 text-xs text-slate-200 focus:outline-none focus:ring-1 focus:ring-accent">
              {cameras.map((d) => <option key={d.device_id} value={d.device_id}>{d.device_id}</option>)}
            </select>
          )}
        </SidebarSection>

        {/* Focuser */}
        <SidebarSection title={t('focuser.title')}>
          {focuserCandidates.length === 0 ? (
            <span className="text-xs text-slate-600">{t('focuser.none')}</span>
          ) : focuserCandidates.length === 1 ? (
            <span className="text-xs text-slate-300 font-mono">{focuserCandidates[0].device_id}</span>
          ) : (
            <select value={focuserId} onChange={(e) => setFocuserId(e.target.value)}
              className="w-full rounded bg-surface-overlay border border-surface-border px-2 py-1.5 text-xs text-slate-200 focus:outline-none focus:ring-1 focus:ring-accent">
              {focuserCandidates.map((d) => <option key={d.device_id} value={d.device_id}>{d.device_id}</option>)}
            </select>
          )}
        </SidebarSection>

        {/* V-curve configuration */}
        <SidebarSection title={t('vcurve.title')}>
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
            <IntegerStepper
              label={t('vcurve.stepSize')}
              unit={t('vcurve.steps')}
              value={settings.step_size}
              onChange={(v) => patchSettings('step_size', Math.max(1, v))}
              progression={STEP_SIZE_PROGRESSION}
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
                  className="flex-1 accent-accent h-1"
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
        <SidebarSection title={t('exposure.title')}>
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
                  className="w-full rounded bg-surface-overlay border border-surface-border px-2 py-1.5 text-xs text-slate-200 focus:outline-none focus:ring-1 focus:ring-accent"
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

        {/* Action */}
        <div className="px-4 py-3 border-b border-surface-border flex flex-col gap-2">
          {error && <p className="text-xs text-red-400">{error}</p>}
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
                <div className="h-1.5 bg-surface-overlay rounded-full overflow-hidden">
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

              {run.error && <p className="text-xs text-red-400 break-words">{run.error}</p>}
            </div>
          </SidebarSection>
        )}

        {/* V-curve chart */}
        {run && run.data_points.length > 0 && (
          <SidebarSection title={t('vcurve.title')}>
            <UCurveChart
              dataPoints={run.data_points}
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
              </div>
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
