import { useEffect, useRef, useState } from 'react'
import { Crosshair, Pause, Play, Settings, Square, Target, Wifi, WifiOff } from 'lucide-react'
import { useStore } from '@/store'
import { Button } from '@/components/ui/button'
import type { Phd2Settings } from '@/api/types'
import * as phd2Api from './api'
import type { GuidePoint, Phd2PluginState } from './api'
import { DEFAULT_PHD2_STATE } from './api'

// ── Graph constants ────────────────────────────────────────────────────────────

const GRAPH_H  = 130
const MARGIN_L = 28   // left margin inside SVG coordinate space for y-axis labels
const X_AXIS_H = 14   // extra height below the graph for x-axis tick labels

const GRAPH_SCALES: Array<{ label: string; range: number }> = [
  { label: '±0.5"', range: 1.0 },
  { label: '±1"',   range: 2.0 },
  { label: '±2"',   range: 4.0 },
  { label: '±3"',   range: 6.0 },
]

const SAMPLE_OPTIONS = [50, 100, 200, 500]

// ── Helpers ───────────────────────────────────────────────────────────────────

function lsGet(key: string, fallback: string): string {
  try { return localStorage.getItem(key) ?? fallback } catch { return fallback }
}
function lsSet(key: string, value: string): void {
  try { localStorage.setItem(key, value) } catch { /* ignore */ }
}

/** Format as negative elapsed label, e.g. "-1m30s", "-45s", "0" */
function fmtAgo(secondsAgo: number): string {
  if (secondsAgo < 1) return '0'
  if (secondsAgo < 60) return `-${Math.round(secondsAgo)}s`
  const m = Math.floor(secondsAgo / 60)
  const s = Math.round(secondsAgo % 60)
  return s === 0 ? `-${m}m` : `-${m}m${s}s`
}

// ── Toggle switch (local — same pattern as Mount page) ────────────────────────

function ToggleSwitch({ checked, onChange, label }: {
  checked: boolean; onChange: () => void; label: string
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={onChange}
      className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors focus:outline-none cursor-pointer
        ${checked ? 'bg-accent' : 'bg-surface-border'}`}
      aria-label={label}
    >
      <span className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition-transform
        ${checked ? 'translate-x-[22px]' : 'translate-x-0.5'}`}
      />
    </button>
  )
}

// ── Guide graph ───────────────────────────────────────────────────────────────

function GuideGraph({ points, range, rmsTotal }: {
  points: GuidePoint[]
  range: number
  rmsTotal: number | null | undefined
}) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const [W, setW] = useState(400)

  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const ro = new ResizeObserver(entries => {
      const w = Math.round(entries[0].contentRect.width)
      if (w > 0) setW(w)
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  if (points.length === 0) {
    return (
      <div ref={wrapRef} className="flex items-center justify-center h-24 text-xs text-slate-600">
        No guide data
      </div>
    )
  }

  const halfRange = range / 2
  // Width available for the actual data area (right of y-axis labels)
  const dataW = W - MARGIN_L

  // arcsec value → SVG y (positive arcsec = up = smaller y)
  const toY = (v: number): number => GRAPH_H / 2 - (v / halfRange) * (GRAPH_H / 2)

  // point index → SVG x, offset by MARGIN_L so labels fit inside the SVG
  const n = points.length
  const toX = (i: number): number =>
    MARGIN_L + (n <= 1 ? dataW / 2 : Math.round((i / (n - 1)) * dataW))

  // Horizontal grid lines every 0.5" (0.25" for tight scale)
  const gridStep = range <= 1.0 ? 0.25 : 0.5
  const gridLines: number[] = []
  for (let v = -halfRange; v <= halfRange + 0.0001; v += gridStep) {
    gridLines.push(Math.round(v * 1000) / 1000)
  }

  // Data paths
  const raPath  = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${toX(i)},${toY(p.ra).toFixed(1)}`).join(' ')
  const decPath = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${toX(i)},${toY(p.dec).toFixed(1)}`).join(' ')

  // X-axis: 0 at the right ("now"), negative values going left
  // Up to 5 ticks; use array index as React key so elements are stable DOM nodes
  // that just get their content updated — avoids repaint artifacts from key churn.
  const xTicks: Array<{ x: number; label: string }> = []
  if (n > 1) {
    const tLast = Date.parse(points[n - 1].ts)
    const numTicks = Math.min(5, n)
    for (let t = 0; t < numTicks; t++) {
      const idx   = Math.round(t * (n - 1) / (numTicks - 1))
      const secsAgo = (tLast - Date.parse(points[idx].ts)) / 1000
      xTicks.push({ x: toX(idx), label: fmtAgo(secsAgo) })
    }
  }

  // RMS average band: symmetric dashed lines at ±rmsTotal clamped to graph bounds
  const rmsY    = rmsTotal != null && rmsTotal > 0 ? Math.max(0, Math.min(GRAPH_H, toY(rmsTotal)))  : null
  const rmsYNeg = rmsTotal != null && rmsTotal > 0 ? Math.max(0, Math.min(GRAPH_H, toY(-rmsTotal))) : null

  return (
    // No pl-6 / overflow="visible" — MARGIN_L is baked into the SVG coordinate space
    <div ref={wrapRef} className="w-full">
      <svg width={W} height={GRAPH_H + X_AXIS_H} viewBox={`0 0 ${W} ${GRAPH_H + X_AXIS_H}`}>

        {/* Horizontal grid lines (start at MARGIN_L so they don't overlap labels) */}
        {gridLines.map(v => {
          const y = toY(v)
          const isZero = Math.abs(v) < 0.001
          return (
            <line key={v}
              x1={MARGIN_L} y1={y} x2={W} y2={y}
              stroke={isZero ? '#334155' : '#1e293b'}
              strokeWidth={isZero ? 1 : 0.5}
              strokeDasharray={isZero ? '4 4' : undefined}
            />
          )
        })}

        {/* Y-axis labels inside the left margin */}
        {gridLines.filter(v => Math.abs(v) > 0.001).map(v => (
          <text key={v} x={MARGIN_L - 4} y={toY(v) + 3} fontSize="8" fill="#475569" textAnchor="end">
            {v > 0 ? `+${v}` : `${v}`}
          </text>
        ))}

        {/* RMS average band */}
        {rmsY != null && rmsYNeg != null && (
          <>
            <line x1={MARGIN_L} y1={rmsY} x2={W} y2={rmsY}
              stroke="#94a3b8" strokeWidth={1} strokeDasharray="4 4" />
            <line x1={MARGIN_L} y1={rmsYNeg} x2={W} y2={rmsYNeg}
              stroke="#94a3b8" strokeWidth={1} strokeDasharray="4 4" />
            <text x={W - 2} y={rmsY - 3} fontSize="8" fill="#94a3b8" textAnchor="end">
              ±{rmsTotal!.toFixed(2)}&quot;
            </text>
          </>
        )}

        {/* RA (blue) and Dec (red) data paths */}
        <path d={raPath}  fill="none" stroke="#60a5fa" strokeWidth={1.5} />
        <path d={decPath} fill="none" stroke="#f87171" strokeWidth={1.5} />

        {/* X-axis temporal labels — keyed by index so DOM nodes are stable */}
        {xTicks.map(({ x, label }, idx) => (
          <text key={idx} x={x} y={GRAPH_H + 11} fontSize="8" fill="#475569" textAnchor="middle">
            {label}
          </text>
        ))}

        {/* Legend */}
        <text x={MARGIN_L + 4}  y={10} fontSize="9" fill="#60a5fa">RA</text>
        <text x={MARGIN_L + 22} y={10} fontSize="9" fill="#f87171">Dec</text>
        {rmsY != null && (
          <text x={MARGIN_L + 44} y={10} fontSize="9" fill="#94a3b8">RMS avg</text>
        )}
      </svg>
    </div>
  )
}

// ── Status badge ──────────────────────────────────────────────────────────────

function StateBadge({ state, connected }: { state: string; connected: boolean }) {
  const colour = !connected
    ? 'text-slate-500 border-slate-700'
    : state === 'Guiding'
      ? 'text-green-400 border-green-700'
      : state === 'Paused'
        ? 'text-yellow-400 border-yellow-700'
        : state === 'Star loss'
          ? 'text-red-400 border-red-700'
          : 'text-slate-400 border-slate-600'

  return (
    <span className={`text-xs font-mono px-2 py-0.5 rounded border ${colour}`}>
      {connected ? state : 'Disconnected'}
    </span>
  )
}

// ── Metric row ────────────────────────────────────────────────────────────────

function Metric({ label, value, unit }: { label: string; value: number | null | undefined; unit?: string }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-xs text-slate-500">{label}</span>
      <span className="text-xs font-mono text-slate-200">
        {value != null ? `${value.toFixed(3)}${unit ?? ''}` : '—'}
      </span>
    </div>
  )
}

// ── Event log ─────────────────────────────────────────────────────────────────

function Phd2EventLog() {
  const log = useStore((s) => s.log.filter((e) => e.component === 'phd2'))
  return (
    <div className="h-28 bg-surface border-t border-surface-border overflow-y-auto px-3 py-2 font-mono shrink-0">
      {log.map((e) => (
        <div key={e.id} className="flex gap-2 text-xs leading-5">
          <span className="text-slate-600 shrink-0">{e.timestamp.slice(11, 19)}</span>
          <span className="text-slate-400 truncate">{e.message}</span>
        </div>
      ))}
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

// TODO: audit Connect/Disconnect button style against Equipment page for consistency

export function Phd2Page() {
  const allGuidePoints = useStore((s) => (s.pluginStates['phd2'] as Phd2PluginState | null)?.guidePoints ?? [])
  const status         = useStore((s) => (s.pluginStates['phd2'] as Phd2PluginState | null)?.status ?? null)

  const [error, setError] = useState<string | null>(null)
  const [showSettings, setShowSettings] = useState(false)

  // Connection settings (persisted via backend plugin settings)
  const [phd2Settings, setPhd2Settings] = useState<Phd2Settings>({ host: 'localhost', port: 4400 })
  const [settingsSaving, setSettingsSaving] = useState(false)
  useEffect(() => {
    phd2Api.getSettings()
      .then((s) => setPhd2Settings({ host: s.host ?? 'localhost', port: s.port ?? 4400 }))
      .catch(() => {})
  }, [])
  const savePhd2Settings = async () => {
    setSettingsSaving(true)
    try { await phd2Api.putSettings(phd2Settings) } catch { /* ignore */ } finally { setSettingsSaving(false) }
  }

  // UI preferences persisted via localStorage (graph display only — not server state)
  const [graphRange, setGraphRange] = useState(() =>
    parseFloat(lsGet('phd2_graph_range', '2.0'))
  )
  const [maxSamples, setMaxSamples] = useState(() =>
    parseInt(lsGet('phd2_max_samples', '100'), 10)
  )

  // Debug state: server is the source of truth (returned in status.debug_enabled).
  // Optimistic local copy so the toggle feels instant; reverts on API error.
  // When the server restarts (debug_enabled resets to false), the next status poll
  // updates this automatically — no stale localStorage involved.
  const [debugEnabled, setDebugEnabled] = useState(false)
  useEffect(() => {
    if (status != null) setDebugEnabled(status.debug_enabled)
  }, [status?.debug_enabled])  // eslint-disable-line react-hooks/exhaustive-deps

  // Slice the store's large ring buffer to the user-configured window
  const guidePoints = allGuidePoints.slice(-maxSamples)

  // Poll /phd2/status every 3 s to get RMS values (not emitted via WS)
  useEffect(() => {
    const poll = () => {
      phd2Api.status()
        .then((newStatus) => {
          useStore.setState((s) => {
            const cur = (s.pluginStates['phd2'] as Phd2PluginState | null) ?? DEFAULT_PHD2_STATE
            return { pluginStates: { ...s.pluginStates, phd2: { ...cur, status: newStatus } } }
          })
        })
        .catch(() => {})
    }
    poll()
    const id = setInterval(poll, 3_000)
    return () => clearInterval(id)
  }, [])

  const act = async (fn: () => Promise<void>) => {
    setError(null)
    try { await fn() } catch (e) { setError((e as Error).message) }
  }

  const toggleDebug = async () => {
    const next = !debugEnabled
    setDebugEnabled(next)   // optimistic
    try {
      await phd2Api.setDebug(next)
    } catch (e) {
      setDebugEnabled(!next)  // revert on error
      setError((e as Error).message)
    }
  }

  const handleGraphRangeChange = (range: number) => {
    setGraphRange(range)
    lsSet('phd2_graph_range', String(range))
  }

  const handleMaxSamplesChange = (n: number) => {
    setMaxSamples(n)
    lsSet('phd2_max_samples', String(n))
  }

  const guiding    = status?.state === 'Guiding'
  const paused     = status?.state === 'Paused'
  const connected  = status?.connected ?? false
  const dithering  = status?.is_dithering ?? false

  return (
    <div className="flex flex-col h-full">
    <div className="p-4 max-w-2xl mx-auto w-full flex flex-col gap-4 flex-1 overflow-y-auto">

      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Crosshair size={20} className="text-accent" />
          <h1 className="text-base font-semibold text-slate-200">PHD2 Guiding</h1>
          {status && <StateBadge state={status.state} connected={status.connected} />}
        </div>
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant={connected ? 'danger' : 'outline'}
            onClick={() => act(connected ? phd2Api.disconnect : phd2Api.connect)}
          >
            {connected
              ? <><WifiOff size={12} className="mr-1" /> Disconnect</>
              : <><Wifi size={12} className="mr-1" /> Connect</>
            }
          </Button>
          <Button
            size="icon"
            variant="ghost"
            onClick={() => setShowSettings((v) => !v)}
            title="Graph & debug settings"
            className={showSettings ? 'text-accent' : ''}
          >
            <Settings size={15} />
          </Button>
        </div>
      </div>

      {/* Settings panel */}
      {showSettings && (
        <div className="border border-surface-border rounded-lg p-3 bg-surface-raised flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <span className="text-xs text-slate-400">PHD2 host</span>
            <input
              className="rounded border border-surface-border bg-surface-overlay px-2 py-1 text-xs text-slate-200 font-mono w-36 focus:outline-none focus:ring-1 focus:ring-accent"
              value={phd2Settings.host}
              onChange={(e) => setPhd2Settings((s) => ({ ...s, host: e.target.value }))}
              onBlur={savePhd2Settings}
            />
          </div>
          <div className="flex items-center justify-between">
            <span className="text-xs text-slate-400">PHD2 port</span>
            <input
              type="number"
              className="rounded border border-surface-border bg-surface-overlay px-2 py-1 text-xs text-slate-200 font-mono w-20 focus:outline-none focus:ring-1 focus:ring-accent"
              value={phd2Settings.port}
              onChange={(e) => setPhd2Settings((s) => ({ ...s, port: parseInt(e.target.value) || 4400 }))}
              onBlur={savePhd2Settings}
            />
          </div>
          {settingsSaving && <span className="text-xs text-slate-500">Saving…</span>}
          <div className="border-t border-surface-border" />
          <div className="flex items-center justify-between">
            <span className="text-xs text-slate-400">Graph vertical scale</span>
            <select
              className="rounded bg-surface-overlay border border-surface-border px-2 py-1 text-xs text-slate-200 focus:outline-none"
              value={graphRange}
              onChange={(e) => handleGraphRangeChange(parseFloat(e.target.value))}
            >
              {GRAPH_SCALES.map(({ label, range }) => (
                <option key={range} value={range}>{label}</option>
              ))}
            </select>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-xs text-slate-400">Samples shown</span>
            <select
              className="rounded bg-surface-overlay border border-surface-border px-2 py-1 text-xs text-slate-200 focus:outline-none"
              value={maxSamples}
              onChange={(e) => handleMaxSamplesChange(parseInt(e.target.value, 10))}
            >
              {SAMPLE_OPTIONS.map((n) => (
                <option key={n} value={n}>{n}</option>
              ))}
            </select>
          </div>
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs text-slate-400">PHD2 debug logging</p>
              <p className="text-xs text-slate-600">Prints raw JSON-RPC traffic to the server console</p>
            </div>
            <ToggleSwitch checked={debugEnabled} onChange={toggleDebug} label="PHD2 debug logging" />
          </div>
        </div>
      )}

      {/* Guide graph — full available width */}
      <div className="border border-surface-border rounded p-3 bg-surface-raised">
        <p className="text-xs text-slate-500 mb-2">Guide error (arcsec)</p>
        <GuideGraph points={guidePoints} range={graphRange} rmsTotal={status?.rms_total} />
      </div>

      {/* Metrics */}
      <div className="border border-surface-border rounded p-3 bg-surface-raised flex flex-col gap-1.5">
        <Metric label="RMS RA"      value={status?.rms_ra}    unit={'"'} />
        <Metric label="RMS Dec"     value={status?.rms_dec}   unit={'"'} />
        <Metric label="RMS average" value={status?.rms_total} unit={'"'} />
        <div className="border-t border-surface-border my-1" />
        <Metric label="Star SNR" value={status?.star_snr} />
        <div className="flex items-center justify-between">
          <span className="text-xs text-slate-500">Pixel scale</span>
          <span className="text-xs font-mono text-slate-200">
            {status?.pixel_scale != null ? `${status.pixel_scale.toFixed(2)}" /px` : '—'}
          </span>
        </div>
      </div>

      {/* Controls */}
      <div className="flex flex-col gap-2">
        <div className="flex gap-2 flex-wrap">
          <Button
            size="sm"
            onClick={() => act(() => phd2Api.guide())}
            disabled={!connected || (guiding && !paused)}
          >
            <Play size={12} className="mr-1" /> Guide
          </Button>

          <Button
            size="sm"
            variant="outline"
            onClick={() => act(paused ? phd2Api.resume : phd2Api.pause)}
            disabled={!connected || (!guiding && !paused)}
          >
            {paused
              ? <><Play size={12} className="mr-1" /> Resume</>
              : <><Pause size={12} className="mr-1" /> Pause</>
            }
          </Button>

          <Button
            size="sm"
            variant="danger"
            onClick={() => act(phd2Api.stop)}
            disabled={!connected || (!guiding && !paused)}
          >
            <Square size={12} className="mr-1" /> Stop
          </Button>

          <Button
            size="sm"
            variant="outline"
            onClick={() => act(() => phd2Api.dither())}
            disabled={!connected || !guiding || dithering}
            title={dithering ? 'Dither already in progress' : 'Dither once'}
          >
            <Target size={12} className="mr-1" />
            {dithering ? 'Dithering…' : 'Dither'}
          </Button>
        </div>
        {error && <p className="text-xs text-status-error">{error}</p>}
      </div>

      {!connected && (
        <p className="text-xs text-slate-500">
          PHD2 not connected. Configure host/port in Options → Settings, then click Connect.
        </p>
      )}
    </div>
    <Phd2EventLog />
    </div>
  )
}
