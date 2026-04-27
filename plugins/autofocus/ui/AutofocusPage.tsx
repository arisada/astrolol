import { useCallback, useEffect, useRef, useState } from 'react'
import { ChevronDown, ChevronUp, Focus, StopCircle } from 'lucide-react'
import { api } from '@/api/client'
import * as autofocusApi from './api'
import { useStore } from '@/store'
import { Button } from '@/components/ui/button'
import type {
  AutofocusConfig,
  AutofocusRun,
  AutofocusSettings,
  CurveFit,
  FilterWheelStatus,
  FitAlgo,
  FocusDataPoint,
} from '@/api/types'

// ── Exposure duration stepper ─────────────────────────────────────────────────

const EXPOSURE_STEPS = [0.5, 1, 1.5, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 30]

function fmtDuration(s: number): string {
  return s < 1 ? `${Math.round(s * 1000)} ms` : `${s} s`
}

function DurationStepper({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  const idx = EXPOSURE_STEPS.reduce(
    (best, v, i) => Math.abs(v - value) < Math.abs(EXPOSURE_STEPS[best] - value) ? i : best, 0,
  )
  return (
    <div className="flex items-center gap-1">
      <Button size="icon" variant="outline" disabled={idx === 0}
        onClick={() => onChange(EXPOSURE_STEPS[idx - 1])}><ChevronDown size={13} /></Button>
      <span className="flex-1 text-center text-xs font-mono text-slate-200 bg-surface-overlay border border-surface-border rounded px-2 py-1.5">
        {fmtDuration(value)}
      </span>
      <Button size="icon" variant="outline" disabled={idx === EXPOSURE_STEPS.length - 1}
        onClick={() => onChange(EXPOSURE_STEPS[idx + 1])}><ChevronUp size={13} /></Button>
    </div>
  )
}

// ── U-curve SVG chart ─────────────────────────────────────────────────────────

function UCurveChart({
  dataPoints,
  curveFit,
  optimal,
  fitAlgo,
}: {
  dataPoints: FocusDataPoint[]
  curveFit: CurveFit | null
  optimal: number | null
  fitAlgo: FitAlgo
}) {
  const W = 260, H = 150
  const pad = { t: 8, r: 10, b: 24, l: 34 }
  const cw = W - pad.l - pad.r
  const ch = H - pad.t - pad.b

  if (dataPoints.length === 0) {
    return (
      <div className="flex items-center justify-center h-[150px] text-xs text-slate-600">
        No data yet
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
        transform={`rotate(-90 7 ${pad.t + ch / 2})`}>FWHM px</text>

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

// ── Sidebar section wrapper ───────────────────────────────────────────────────

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="px-4 py-3 border-b border-surface-border">
      <p className="text-[10px] uppercase tracking-widest text-slate-500 mb-2">{title}</p>
      {children}
    </div>
  )
}

// ── Status badge ──────────────────────────────────────────────────────────────

function RunBadge({ status }: { status: AutofocusRun['status'] }) {
  const styles: Record<AutofocusRun['status'], string> = {
    running:   'bg-amber-500/20 text-amber-400 animate-pulse',
    completed: 'bg-green-500/20 text-green-400',
    failed:    'bg-red-500/20 text-red-400',
    aborted:   'bg-slate-500/20 text-slate-400',
  }
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${styles[status]}`}>
      {status}
    </span>
  )
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
}

// ── Main page component ───────────────────────────────────────────────────────

export function AutofocusPage() {
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
    if (!focuserId && focusers.length > 0) setFocuserId(focusers[0].device_id)
  }, [focusers])  // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (filterWheels.length === 0) return
    api.filterWheel.status(filterWheels[0].device_id)
      .then(setFilterWheelStatus)
      .catch(() => {})
  }, [filterWheels])

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
    if (!cameraId || !focuserId) { setError('Camera and focuser must be connected.'); return }
    setError(null)
    setBusy(true)
    setRun(null)
    setPreviewStep(null)

    // Persist settings before starting
    autofocusApi.putSettings(settings).catch(() => {})

    const config: AutofocusConfig = {
      camera_id: cameraId,
      focuser_id: focuserId,
      ...settings,
    }

    try {
      const r = await autofocusApi.start(config)
      setRun(r)
      pollRef.current = setInterval(fetchRun, 1500)
    } catch (err) {
      setBusy(false)
      setError(err instanceof Error ? err.message : 'Failed to start autofocus')
    }
  }, [cameraId, focuserId, settings, fetchRun])

  const handleAbort = useCallback(async () => {
    try { await autofocusApi.abort(); await fetchRun() }
    catch { setBusy(false) }
  }, [fetchRun])

  // ── Derived display values ─────────────────────────────────────────────────
  // Use the last *completed* data point — run.current_step is set at the
  // start of each iteration before exposure/preview are ready.
  const lastDp      = run?.data_points.length ? run.data_points[run.data_points.length - 1] : null
  const displayStep = previewStep ?? lastDp?.step ?? null
  const previewUrl  = displayStep ? `${autofocusApi.previewUrl(displayStep)}?k=${previewKey}` : null

  const bestDataPoint = run?.data_points.filter((d) => d.fwhm > 0).reduce(
    (best, dp) => (!best || dp.fwhm < best.fwhm ? dp : best), null as FocusDataPoint | null,
  )

  const BINNINGS = [1, 2, 3, 4]

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className="flex h-full overflow-hidden bg-surface-bg">

      {/* ── Left: image preview ── */}
      <div className="flex-1 flex flex-col items-center justify-center bg-black min-w-0 relative">
        {previewUrl ? (
          <img src={previewUrl} alt="Focus step" className="max-w-full max-h-full object-contain" />
        ) : (
          <div className="flex flex-col items-center gap-3 text-slate-600">
            <Focus size={48} strokeWidth={1} />
            <p className="text-sm">Start an autofocus run to see the image</p>
          </div>
        )}

        {/* Step selector thumbnails */}
        {run && run.data_points.length > 1 && (
          <div className="absolute bottom-0 left-0 right-0 flex gap-1 px-3 py-2 bg-gradient-to-t from-black/80 overflow-x-auto">
            {run.data_points.map((dp) => (
              <button
                key={dp.step}
                onClick={() => setPreviewStep(dp.step)}
                title={`Step ${dp.step}: pos ${dp.position}, FWHM ${dp.fwhm.toFixed(2)}`}
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
      <aside className="w-72 flex flex-col overflow-y-auto border-l border-surface-border bg-surface-panel">

        {/* Camera */}
        <Section title="Camera">
          {cameras.length === 0 ? (
            <span className="text-xs text-slate-600">No camera connected</span>
          ) : cameras.length === 1 ? (
            <span className="text-xs text-slate-300 font-mono">{cameras[0].device_id}</span>
          ) : (
            <select value={cameraId} onChange={(e) => setCameraId(e.target.value)}
              className="w-full rounded bg-surface-overlay border border-surface-border px-2 py-1.5 text-xs text-slate-200 focus:outline-none focus:ring-1 focus:ring-accent">
              {cameras.map((d) => <option key={d.device_id} value={d.device_id}>{d.device_id}</option>)}
            </select>
          )}
        </Section>

        {/* Focuser */}
        <Section title="Focuser">
          {focusers.length === 0 ? (
            <span className="text-xs text-slate-600">No focuser connected</span>
          ) : focusers.length === 1 ? (
            <span className="text-xs text-slate-300 font-mono">{focusers[0].device_id}</span>
          ) : (
            <select value={focuserId} onChange={(e) => setFocuserId(e.target.value)}
              className="w-full rounded bg-surface-overlay border border-surface-border px-2 py-1.5 text-xs text-slate-200 focus:outline-none focus:ring-1 focus:ring-accent">
              {focusers.map((d) => <option key={d.device_id} value={d.device_id}>{d.device_id}</option>)}
            </select>
          )}
        </Section>

        {/* V-curve configuration */}
        <Section title="V-Curve">
          <div className="flex flex-col gap-3">

            {/* Algorithm selector */}
            <div className="flex flex-col gap-1">
              <label className="text-xs text-slate-400">Fit algorithm</label>
              <div className="flex gap-1">
                {(['parabola', 'hyperbola'] as FitAlgo[]).map((algo) => (
                  <button key={algo} type="button" onClick={() => patchSettings('fit_algo', algo)}
                    className={`flex-1 py-0.5 text-xs rounded border capitalize transition-colors ${
                      settings.fit_algo === algo
                        ? 'border-accent text-accent bg-accent/10'
                        : 'border-surface-border text-slate-400 hover:border-slate-500 hover:text-slate-300'
                    }`}>
                    {algo}
                  </button>
                ))}
              </div>
            </div>

            {/* Step size */}
            <div className="flex flex-col gap-1">
              <label className="text-xs text-slate-400">Step size</label>
              <div className="flex items-center gap-1">
                <input
                  type="number" min={1} value={settings.step_size}
                  onChange={(e) => patchSettings('step_size', Math.max(1, parseInt(e.target.value, 10) || 1))}
                  className="flex-1 bg-surface-overlay border border-surface-border rounded px-2 py-1 text-xs text-slate-200 font-mono focus:outline-none focus:ring-1 focus:ring-accent"
                />
                <span className="text-xs text-slate-500">steps</span>
              </div>
            </div>

            {/* Steps each side */}
            <div className="flex flex-col gap-1">
              <label className="text-xs text-slate-400">
                Steps each side — <span className="text-slate-300">{settings.num_steps * 2 + 1} total</span>
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
          </div>
        </Section>

        {/* Exposure */}
        <Section title="Exposure">
          <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-1">
              <label className="text-xs text-slate-400">Duration</label>
              <DurationStepper value={settings.exposure_time} onChange={(v) => patchSettings('exposure_time', v)} />
            </div>

            <div className="flex flex-col gap-1">
              <label className="text-xs text-slate-400">Binning</label>
              <div className="flex gap-1">
                {BINNINGS.map((b) => (
                  <button key={b} type="button" onClick={() => patchSettings('binning', b)}
                    className={`px-2 py-0.5 text-xs rounded border transition-colors ${
                      settings.binning === b
                        ? 'border-accent text-accent bg-accent/10'
                        : 'border-surface-border text-slate-400 hover:border-slate-500 hover:text-slate-300'
                    }`}>
                    {b}×{b}
                  </button>
                ))}
              </div>
            </div>

            <div className="flex flex-col gap-1">
              <label className="text-xs text-slate-400">Gain <span className="text-slate-600">(optional)</span></label>
              <input
                type="number" min={0} placeholder="driver default"
                value={settings.gain ?? ''}
                onChange={(e) => patchSettings('gain', e.target.value ? parseInt(e.target.value, 10) : null)}
                className="w-full bg-surface-overlay border border-surface-border rounded px-2 py-1 text-xs text-slate-200 font-mono placeholder-slate-600 focus:outline-none focus:ring-1 focus:ring-accent"
              />
            </div>

            {filterWheels.length > 0 && (
              <div className="flex flex-col gap-1">
                <label className="text-xs text-slate-400">Filter <span className="text-slate-600">(optional)</span></label>
                <select
                  value={settings.filter_slot ?? ''}
                  onChange={(e) => patchSettings('filter_slot', e.target.value ? parseInt(e.target.value, 10) : null)}
                  className="w-full rounded bg-surface-overlay border border-surface-border px-2 py-1.5 text-xs text-slate-200 focus:outline-none focus:ring-1 focus:ring-accent"
                >
                  <option value="">Keep current</option>
                  {filterWheelStatus?.filter_names.length
                    ? filterWheelStatus.filter_names.map((name, i) => (
                        <option key={i + 1} value={i + 1}>{name}</option>
                      ))
                    : Array.from({ length: filterWheelStatus?.filter_count ?? 5 }, (_, i) => (
                        <option key={i + 1} value={i + 1}>Slot {i + 1}</option>
                      ))
                  }
                </select>
              </div>
            )}
          </div>
        </Section>

        {/* Action */}
        <div className="px-4 py-3 border-b border-surface-border flex flex-col gap-2">
          {error && <p className="text-xs text-red-400">{error}</p>}
          <Button
            onClick={handleStart}
            disabled={busy || cameras.length === 0 || focusers.length === 0}
            className="w-full"
          >
            <Focus size={13} className="mr-2" />
            {busy ? 'Running…' : 'Start Autofocus'}
          </Button>
          {busy && (
            <Button variant="danger" onClick={handleAbort} className="w-full">
              <StopCircle size={13} className="mr-2" />
              Abort
            </Button>
          )}
        </div>

        {/* Progress */}
        {run && (
          <Section title="Progress">
            <div className="flex flex-col gap-2">
              <div className="flex items-center justify-between">
                <span className="text-xs text-slate-300">
                  {run.status === 'running'
                    ? `Step ${run.current_step} / ${run.total_steps}`
                    : `${run.total_steps} steps`}
                </span>
                <RunBadge status={run.status} />
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
                return (
                  <div className="text-xs text-slate-400 space-y-0.5">
                    <div>Position: <span className="text-slate-200 font-mono">{latest.position}</span></div>
                    <div>
                      FWHM:{' '}
                      <span className={`font-mono ${latest === bestDataPoint ? 'text-green-400' : 'text-slate-200'}`}>
                        {latest.fwhm > 0 ? `${latest.fwhm.toFixed(2)} px` : '—'}
                      </span>
                    </div>
                    <div>Stars: <span className="text-slate-200 font-mono">{latest.star_count}</span></div>
                  </div>
                )
              })()}

              {run.error && <p className="text-xs text-red-400 break-words">{run.error}</p>}
            </div>
          </Section>
        )}

        {/* V-curve chart */}
        {run && run.data_points.length > 0 && (
          <Section title="V-Curve">
            <UCurveChart
              dataPoints={run.data_points}
              curveFit={run.curve_fit}
              optimal={run.optimal_position}
              fitAlgo={run.config.fit_algo ?? 'parabola'}
            />
          </Section>
        )}

        {/* Result */}
        {run?.status === 'completed' && run.optimal_position !== null && (
          <Section title="Result">
            <div className="flex flex-col gap-1.5">
              <div className="flex items-baseline gap-2">
                <span className="text-xs text-slate-400">Optimal position:</span>
                <span className="text-lg font-mono text-green-400">{run.optimal_position}</span>
              </div>
              {bestDataPoint && (
                <div className="text-xs text-slate-500">
                  Best FWHM: <span className="text-slate-300 font-mono">{bestDataPoint.fwhm.toFixed(2)} px</span>
                  {' '}at {bestDataPoint.position}
                </div>
              )}
            </div>
          </Section>
        )}

      </aside>
    </div>
  )
}
