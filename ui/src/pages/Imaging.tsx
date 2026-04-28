import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import {
  Camera, ChevronDown, ChevronUp, Crosshair, Play, Settings, Square, StopCircle, Thermometer,
} from 'lucide-react'
import { api } from '@/api/client'
import { useStore } from '@/store'
import type { CameraStatus, DitherConfig, FilterWheelStatus, FrameType, ImageStats, ImagerDeviceSettings } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { DevicePropertiesPanel } from '@/components/DevicePropertiesPanel'

// ── localStorage persistence (focuser step only) ──────────────────────────────

function useLocalStorage<T>(key: string, initial: T): [T, (v: T) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      const stored = localStorage.getItem(key)
      return stored !== null ? (JSON.parse(stored) as T) : initial
    } catch {
      return initial
    }
  })
  const set = useCallback((v: T) => {
    setValue(v)
    try { localStorage.setItem(key, JSON.stringify(v)) } catch { /* storage full */ }
  }, [key])
  return [value, set]
}

const DEFAULT_IMAGER_SETTINGS: ImagerDeviceSettings = {
  duration: 5,
  binning: 1,
  frame_type: 'light',
  save_subs: true,
  dither_frames: '',
  dither_minutes: '',
  histo_auto: true,
  target_temp: '',
}

// ── Exposure duration helpers ─────────────────────────────────────────────────

const EXPOSURE_STEPS = [
  0.001, 0.002, 0.003, 0.004, 0.005, 0.008,
  0.01, 0.013, 0.015, 0.02, 0.025, 0.033, 0.04, 0.05,
  0.067, 0.08, 0.1, 0.125, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5, 0.6, 0.8,
  1, 1.5, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30,
  45, 60, 90, 120, 180, 240, 300, 360, 480, 600, 900, 1200, 1800, 3600,
]

function fmtDuration(s: number): string {
  if (s < 1) return `${Math.round(s * 1000)} ms`
  if (s < 60) return `${s} s`
  const m = Math.floor(s / 60)
  const rem = s % 60
  return rem === 0 ? `${m} m` : `${m} m ${rem} s`
}

// ── Shared sub-components ─────────────────────────────────────────────────────

function Panel({
  title, deviceId, onSettings, children,
}: {
  title: string
  deviceId?: string
  onSettings?: (id: string) => void
  children: React.ReactNode
}) {
  return (
    <div className="mx-3 my-2.5 border border-surface-border rounded-lg p-3">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-xs font-medium text-slate-500 uppercase tracking-wider">{title}</h3>
        {deviceId && onSettings && (
          <button
            onClick={() => onSettings(deviceId)}
            title="INDI properties"
            className="text-slate-600 hover:text-slate-400 transition-colors"
          >
            <Settings size={12} />
          </button>
        )}
      </div>
      {children}
    </div>
  )
}

function PillGroup<T extends string>({
  options, value, onChange, label, formatLabel,
}: { options: T[]; value: T; onChange: (v: T) => void; label: string; formatLabel?: (v: T) => string }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs text-slate-400">{label}</span>
      <div className="flex gap-1 flex-wrap">
        {options.map((o) => (
          <button
            key={o}
            type="button"
            onClick={() => onChange(o)}
            className={`px-2 py-0.5 text-xs rounded border transition-colors capitalize
              ${value === o
                ? 'border-accent text-accent bg-accent/10'
                : 'border-surface-border text-slate-400 hover:border-slate-500 hover:text-slate-300'
              }`}
          >
            {formatLabel ? formatLabel(o) : o}
          </button>
        ))}
      </div>
    </div>
  )
}

function TogglePill({ label, value, onChange }: { label: string; value: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      type="button"
      onClick={() => onChange(!value)}
      className={`flex items-center justify-between w-full px-2 py-0.5 text-xs rounded border transition-colors
        ${value
          ? 'border-accent text-accent bg-accent/10'
          : 'border-surface-border text-slate-400 hover:border-slate-500 hover:text-slate-300'
        }`}
    >
      <span>{label}</span>
      <span className="text-slate-500">{value ? 'ON' : 'OFF'}</span>
    </button>
  )
}

function DurationStepper({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  const [editing, setEditing] = useState(false)
  const [raw, setRaw] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  const idx = EXPOSURE_STEPS.reduce(
    (best, v, i) => Math.abs(v - value) < Math.abs(EXPOSURE_STEPS[best] - value) ? i : best, 0,
  )

  const startEdit = () => {
    setRaw(String(value))
    setEditing(true)
    setTimeout(() => inputRef.current?.select(), 0)
  }

  const commitEdit = () => {
    const n = parseFloat(raw)
    if (!isNaN(n) && n > 0) onChange(n)
    setEditing(false)
  }

  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs text-slate-400">Duration</span>
      <div className="flex items-center gap-1">
        <Button size="icon" variant="outline" disabled={idx === 0}
          onClick={() => { setEditing(false); onChange(EXPOSURE_STEPS[idx - 1]) }} title="Shorter">
          <ChevronDown size={14} />
        </Button>
        {editing ? (
          <input
            ref={inputRef}
            type="number" min="0.001" step="any" value={raw}
            onChange={(e) => setRaw(e.target.value)}
            onBlur={commitEdit}
            onKeyDown={(e) => { if (e.key === 'Enter') commitEdit(); if (e.key === 'Escape') setEditing(false) }}
            className="flex-1 text-center text-xs font-mono text-slate-200 bg-surface-overlay border border-accent rounded px-2 py-1.5 min-w-[5rem] focus:outline-none"
          />
        ) : (
          <button type="button" onClick={startEdit} title="Click to enter a custom value"
            className="flex-1 text-center text-xs font-mono text-slate-200 bg-surface-overlay border border-surface-border rounded px-2 py-1.5 min-w-[5rem] hover:border-slate-500 transition-colors">
            {fmtDuration(value)}
          </button>
        )}
        <Button size="icon" variant="outline" disabled={idx === EXPOSURE_STEPS.length - 1}
          onClick={() => { setEditing(false); onChange(EXPOSURE_STEPS[idx + 1]) }} title="Longer">
          <ChevronUp size={14} />
        </Button>
      </div>
    </div>
  )
}

// ── Histogram overlay ─────────────────────────────────────────────────────────

function HistogramOverlay({ stats }: { stats: ImageStats }) {
  const { histogram, hist_min, hist_max, stretch_low, stretch_high } = stats
  const W = 160
  const H = 48
  const maxCount = Math.max(...histogram, 1)
  const range = hist_max - hist_min || 1
  const lowX = Math.max(0, Math.min(W, ((stretch_low - hist_min) / range) * W))
  const highX = Math.max(0, Math.min(W, ((stretch_high - hist_min) / range) * W))
  const bins = histogram.length

  return (
    <svg width={W} height={H} className="block">
      {histogram.map((count, i) => {
        const barH = (count / maxCount) * H
        const x = (i / bins) * W
        const bw = W / bins + 0.5
        return (
          <rect
            key={i}
            x={x} y={H - barH} width={bw} height={barH}
            fill="rgba(200,200,200,0.6)"
          />
        )
      })}
      {/* Stretch clip markers */}
      <line x1={lowX} y1={0} x2={lowX} y2={H} stroke="rgba(96,165,250,0.8)" strokeWidth={1} />
      <line x1={highX} y1={0} x2={highX} y2={H} stroke="rgba(251,191,36,0.8)" strokeWidth={1} />
    </svg>
  )
}

// ── Image Viewer ──────────────────────────────────────────────────────────────

function ImageViewer({ deviceId, histoAuto }: { deviceId: string | undefined; histoAuto: boolean }) {
  const image = useStore((s) => deviceId ? (s.latestImages[deviceId] ?? null) : null)
  const stats = useStore((s) => deviceId ? (s.imageStats[deviceId] ?? null) : null)
  const previewUrl = image
    ? (histoAuto || !image.previewUrlLinear ? image.previewUrl : image.previewUrlLinear)
    : null

  return (
    <div className="flex-1 bg-black flex items-center justify-center relative min-h-0">
      {previewUrl ? (
        <>
          <img
            src={previewUrl}
            alt="Latest exposure"
            className="max-w-full max-h-full object-contain"
          />
          {/* Bottom-left: image info + FWHM */}
          <div className="absolute bottom-2 left-2 flex flex-col gap-0.5">
            <div className="text-xs text-slate-400 bg-black/60 px-2 py-1 rounded">
              {image!.width}×{image!.height} · {image!.duration}s
              {stats && stats.star_count > 0 && stats.fwhm != null && (
                <span className="ml-2 text-emerald-400">
                  FWHM {stats.fwhm.toFixed(1)}px · {stats.star_count}★
                </span>
              )}
            </div>
          </div>
          {/* Bottom-right: histogram */}
          {stats && (
            <div className="absolute bottom-2 right-2 bg-black/60 rounded p-1">
              <HistogramOverlay stats={stats} />
            </div>
          )}
        </>
      ) : (
        <div className="text-slate-600 text-sm flex flex-col items-center gap-2">
          <Camera size={32} />
          <span>No image yet</span>
        </div>
      )}
    </div>
  )
}

// ── Camera Panel ──────────────────────────────────────────────────────────────

const FRAME_TYPES: FrameType[] = ['light', 'dark', 'flat', 'bias']
const BINNINGS = [1, 2, 3, 4]

function CameraPanel({
  deviceId, name, onSettings, onHistoAutoChange,
}: {
  deviceId: string
  name: string
  onSettings: (id: string) => void
  onHistoAutoChange: (v: boolean) => void
}) {
  const imagerBusy = useStore((s) => s.imagerBusy)
  const busy = imagerBusy[deviceId] ?? false

  // Server-persisted settings — loaded on mount, saved on each change
  const [settings, setSettingsState] = useState<ImagerDeviceSettings>(DEFAULT_IMAGER_SETTINGS)
  const settingsRef = useRef(settings)
  settingsRef.current = settings

  const patchSettings = useCallback((patch: Partial<ImagerDeviceSettings>) => {
    const next = { ...settingsRef.current, ...patch }
    setSettingsState(next)
    api.imager.putSettings(deviceId, next).catch(() => {})
  }, [deviceId])

  // Gain lives in the driver, not in persisted settings.
  const [gain, setGain] = useState(0)
  const [gainPropName, setGainPropName] = useState<string | null>(null)
  const [gainElemName, setGainElemName] = useState<string | null>(null)
  const [gainMin, setGainMin] = useState(0)
  const [gainMax, setGainMax] = useState(65535)
  const [gainStep, setGainStep] = useState(1)
  const [looping, setLooping] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Camera hardware status (temperature, cooler)
  const [cameraStatus, setCameraStatus] = useState<CameraStatus | null>(null)

  useEffect(() => {
    if (!deviceId) return

    // Load persisted settings from server
    api.imager.getSettings(deviceId)
      .then((s) => {
        setSettingsState(s)
        onHistoAutoChange(s.histo_auto)
      })
      .catch(() => {})

    // Sync loop state from server on mount so Stop button is always reachable
    api.imager.status(deviceId)
      .then((s) => { if (s.state === 'looping') setLooping(true) })
      .catch(() => {})

    api.devices.properties(deviceId)
      .then((props) => {
        for (const p of props) {
          if (p.type !== 'number') continue
          const w = p.widgets.find((w) => w.name?.toLowerCase() === 'gain' || w.label?.toLowerCase() === 'gain')
          if (w) {
            if (w.min != null) setGainMin(w.min as number)
            if (w.max != null) setGainMax(w.max as number)
            if (w.step != null && (w.step as number) > 0) setGainStep(w.step as number)
            if (typeof w.value === 'number') setGain(w.value)
            setGainPropName(p.name)
            setGainElemName(w.name ?? null)
            break
          }
        }
      })
      .catch(() => {})

    // Poll camera status for temperature
    const poll = () => {
      api.imager.cameraStatus(deviceId)
        .then(setCameraStatus)
        .catch(() => {})
    }
    poll()
    const id = setInterval(poll, 10_000)
    return () => clearInterval(id)
  }, [deviceId]) // eslint-disable-line react-hooks/exhaustive-deps

  const buildDitherConfig = (): DitherConfig | undefined => {
    const frames = parseInt(settings.dither_frames)
    const minutes = parseFloat(settings.dither_minutes)
    if (!isNaN(frames) && frames > 0) return { every_frames: frames }
    if (!isNaN(minutes) && minutes > 0) return { every_minutes: minutes }
    return undefined
  }

  const commitGain = async (value: number) => {
    if (!gainPropName || !gainElemName) return
    try {
      await api.devices.setProperty(deviceId, gainPropName, { values: { [gainElemName]: value } })
    } catch (e) {
      setError(`Gain: ${(e as Error).message}`)
    }
  }

  const expose = async () => {
    setError(null)
    try {
      await api.imager.expose(deviceId, {
        duration: settings.duration, gain: gainPropName ? gain : null,
        binning: settings.binning, frame_type: settings.frame_type as FrameType, save: settings.save_subs,
      })
    } catch (e) { setError((e as Error).message) }
  }

  const halt = async () => {
    setError(null)
    try {
      await api.imager.halt(deviceId)
      setLooping(false)
    } catch (e) { setError((e as Error).message) }
  }

  const toggleLoop = async () => {
    setError(null)
    try {
      if (looping) {
        await api.imager.stopLoop(deviceId)
        setLooping(false)
      } else {
        await api.imager.startLoop(deviceId, {
          duration: settings.duration, gain: gainPropName ? gain : null,
          binning: settings.binning, frame_type: settings.frame_type as FrameType, save: settings.save_subs,
          dither: buildDitherConfig() ?? null,
        })
        setLooping(true)
      }
    } catch (e) { setError((e as Error).message) }
  }

  const setCooler = async (enabled: boolean) => {
    const temp = parseFloat(settings.target_temp)
    try {
      await api.imager.setCooler(deviceId, enabled, !isNaN(temp) ? temp : undefined)
      setCameraStatus((s) => s ? { ...s, cooler_on: enabled } : s)
    } catch (e) { setError((e as Error).message) }
  }

  const applyTemp = async () => {
    const temp = parseFloat(settings.target_temp)
    if (isNaN(temp)) return
    try {
      await api.imager.setCooler(deviceId, cameraStatus?.cooler_on ?? true, temp)
    } catch (e) { setError((e as Error).message) }
  }

  const hasCooler = cameraStatus?.temperature != null

  return (
    <Panel title={name} deviceId={deviceId} onSettings={onSettings}>
      <div className="flex flex-col gap-3">

        {/* Temperature */}
        {hasCooler && (
          <div className="flex flex-col gap-2 pb-2 border-b border-surface-border">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5 text-xs text-slate-400">
                <Thermometer size={12} />
                <span>{cameraStatus!.temperature?.toFixed(1)}°C</span>
                {cameraStatus!.cooler_power != null && (
                  <span className="text-slate-600">({Math.round(cameraStatus!.cooler_power)}%)</span>
                )}
              </div>
              <button
                onClick={() => setCooler(!cameraStatus!.cooler_on)}
                className={`text-xs px-2 py-0.5 rounded border transition-colors ${
                  cameraStatus!.cooler_on
                    ? 'border-accent text-accent bg-accent/10'
                    : 'border-surface-border text-slate-500'
                }`}
              >
                {cameraStatus!.cooler_on ? 'Cooler ON' : 'Cooler OFF'}
              </button>
            </div>
            {cameraStatus!.cooler_on && (
              <div className="flex gap-1.5">
                <Input
                  type="number" step="0.5" placeholder="Target °C"
                  value={settings.target_temp}
                  onChange={(e) => patchSettings({ target_temp: e.target.value })}
                  className="flex-1 text-xs"
                />
                <Button size="sm" variant="outline" onClick={applyTemp} disabled={!settings.target_temp}>Set</Button>
              </div>
            )}
          </div>
        )}

        {/* Frame type */}
        <PillGroup options={FRAME_TYPES} value={settings.frame_type as FrameType}
          onChange={(v) => patchSettings({ frame_type: v })} label="Frame type" />

        {/* Duration stepper */}
        <DurationStepper value={settings.duration} onChange={(v) => patchSettings({ duration: v })} />

        {/* Gain */}
        <div className="flex flex-col gap-1">
          <div className="flex items-center justify-between">
            <span className="text-xs text-slate-400">Gain</span>
            <span className="text-xs text-slate-600">{gainMin}–{gainMax}</span>
          </div>
          <Input
            type="number" min={gainMin} max={gainMax} step={gainStep} value={gain}
            onChange={(e) => setGain(Math.max(gainMin, Math.min(gainMax, parseInt(e.target.value) || 0)))}
            onBlur={(e) => commitGain(Math.max(gainMin, Math.min(gainMax, parseInt(e.target.value) || 0)))}
            onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
          />
        </div>

        {/* Binning */}
        <PillGroup
          options={BINNINGS.map(String) as string[]}
          value={String(settings.binning)}
          onChange={(v) => patchSettings({ binning: parseInt(v) })}
          label="Binning"
          formatLabel={(v) => `${v}×${v}`}
        />

        {/* Save subs + stretch mode */}
        <div className="flex flex-col gap-1.5">
          <TogglePill label="Save subs" value={settings.save_subs}
            onChange={(v) => patchSettings({ save_subs: v })} />
          <TogglePill label="Auto stretch" value={settings.histo_auto}
            onChange={(v) => { patchSettings({ histo_auto: v }); onHistoAutoChange(v) }} />
        </div>

        {/* Guiding / dither */}
        <div className="border-t border-surface-border pt-2 flex flex-col gap-2">
          <div className="flex items-center gap-1.5">
            <Crosshair size={12} className="text-slate-500" />
            <span className="text-xs text-slate-500 uppercase tracking-wider">Guiding / Dither</span>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div className="flex flex-col gap-1">
              <span className="text-xs text-slate-400">Every N frames</span>
              <Input
                type="number" min="1" step="1" placeholder="—"
                value={settings.dither_frames}
                onChange={(e) => patchSettings({ dither_frames: e.target.value, dither_minutes: e.target.value ? '' : settings.dither_minutes })}
                className="text-xs text-center"
              />
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-xs text-slate-400">Every N minutes</span>
              <Input
                type="number" min="0.1" step="0.5" placeholder="—"
                value={settings.dither_minutes}
                onChange={(e) => patchSettings({ dither_minutes: e.target.value, dither_frames: e.target.value ? '' : settings.dither_frames })}
                className="text-xs text-center"
              />
            </div>
          </div>
        </div>

        {/* Actions */}
        <div className="flex gap-2">
          <Button size="sm" onClick={expose} disabled={busy}>
            <Camera size={12} className="mr-1" /> Expose
          </Button>
          <Button size="sm" variant={looping ? 'danger' : 'outline'} onClick={toggleLoop} disabled={!looping && busy}>
            {looping ? <><Square size={12} className="mr-1" /> Stop</> : <><Play size={12} className="mr-1" /> Loop</>}
          </Button>
          <Button size="sm" variant="danger" onClick={halt} title="Abort exposure and cancel loop immediately">
            <StopCircle size={12} className="mr-1" /> Halt
          </Button>
        </div>
        {error && <p className="text-xs text-status-error">{error}</p>}
      </div>
    </Panel>
  )
}

// ── Focuser Panel ─────────────────────────────────────────────────────────────

function FocuserPanel({
  deviceId, onSettings,
}: {
  deviceId: string
  onSettings: (id: string) => void
}) {
  const focuserStatuses = useStore((s) => s.focuserStatuses)
  const setFocuserStatus = useStore((s) => s.setFocuserStatus)
  const position = focuserStatuses[deviceId]?.position

  const [target, setTarget] = useState('')
  const [step, setStep] = useLocalStorage('imaging.focuserStep', '100')
  const [error, setError] = useState<string | null>(null)

  // Fetch initial position immediately on mount
  useEffect(() => {
    api.focuser.status(deviceId)
      .then((s) => setFocuserStatus(deviceId, s))
      .catch(() => {})
  }, [deviceId, setFocuserStatus])

  const act = async (fn: () => Promise<unknown>) => {
    setError(null)
    try { await fn() } catch (e) { setError((e as Error).message) }
  }

  return (
    <Panel title="Focuser" deviceId={deviceId} onSettings={onSettings}>
      <div className="flex flex-col gap-2">
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-400">Position</span>
          <span className="text-sm font-mono text-slate-200">{position ?? '—'}</span>
        </div>

        <div className="flex items-center gap-2">
          <Button size="icon" variant="outline"
            onClick={() => act(() => api.focuser.moveBy(deviceId, -parseInt(step)))} title="Move in">
            <ChevronDown size={14} />
          </Button>
          <Input className="w-20 text-center" type="number" min="1" value={step}
            onChange={(e) => setStep(e.target.value)} />
          <Button size="icon" variant="outline"
            onClick={() => act(() => api.focuser.moveBy(deviceId, parseInt(step)))} title="Move out">
            <ChevronUp size={14} />
          </Button>
          <span className="text-xs text-slate-500">steps</span>
        </div>

        <div className="flex gap-2">
          <Input type="number" min="0" placeholder="Absolute position"
            value={target} onChange={(e) => setTarget(e.target.value)} />
          <Button size="sm"
            onClick={() => act(() => api.focuser.moveTo(deviceId, parseInt(target)))}
            disabled={!target}>Go</Button>
        </div>

        <Button size="sm" variant="danger" onClick={() => act(() => api.focuser.halt(deviceId))}>
          <StopCircle size={12} className="mr-1" /> Halt
        </Button>
        {error && <p className="text-xs text-status-error">{error}</p>}
      </div>
    </Panel>
  )
}

// ── Filter Wheel Panel ────────────────────────────────────────────────────────

function FilterWheelPanel({
  deviceId, onSettings,
}: {
  deviceId: string
  onSettings: (id: string) => void
}) {
  const filterWheelStatuses = useStore((s) => s.filterWheelStatuses)
  const setFilterWheelStatus = useStore((s) => s.setFilterWheelStatus)
  const status: FilterWheelStatus | undefined = filterWheelStatuses[deviceId]
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.filterWheel.status(deviceId)
      .then((s) => setFilterWheelStatus(deviceId, s))
      .catch(() => {})
  }, [deviceId, setFilterWheelStatus])

  const selectFilter = async (slot: number) => {
    setError(null)
    try {
      await api.filterWheel.select(deviceId, slot)
      setFilterWheelStatus(deviceId, { ...status!, current_slot: slot, is_moving: false })
    } catch (e) { setError((e as Error).message) }
  }

  const names = status?.filter_names ?? []
  const count = status?.filter_count ?? names.length
  const slots = Array.from({ length: count }, (_, i) => i + 1)

  return (
    <Panel title="Filter Wheel" deviceId={deviceId} onSettings={onSettings}>
      <div className="flex flex-col gap-2">
        <select
          value={status?.current_slot ?? ''}
          onChange={(e) => selectFilter(parseInt(e.target.value))}
          className="rounded bg-surface-overlay border border-surface-border px-2 py-1.5 text-xs text-slate-200 focus:outline-none focus:ring-1 focus:ring-accent"
          disabled={status?.is_moving}
        >
          {slots.map((slot) => (
            <option key={slot} value={slot}>
              {slot}. {names[slot - 1] ?? `Filter ${slot}`}
            </option>
          ))}
        </select>
        {status?.is_moving && <p className="text-xs text-slate-500">Moving…</p>}
        {error && <p className="text-xs text-status-error">{error}</p>}
      </div>
    </Panel>
  )
}

// ── Event Log ─────────────────────────────────────────────────────────────────

function EventLog() {
  const log = useStore((s) => s.log.filter((e) => e.component === 'imager' || e.component === 'indi' || e.component === 'phd2'))
  return (
    <div className="h-28 bg-surface border-t border-surface-border overflow-y-auto px-3 py-2 font-mono">
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

export function Imaging() {
  const { deviceId } = useParams<{ deviceId?: string }>()
  const connectedDevices = useStore((s) => s.connectedDevices)

  // histoAuto is lifted here so ImageViewer can read it.
  // CameraPanel sets it via onHistoAutoChange when it loads or toggles.
  const [histoAuto, setHistoAuto] = useState(true)

  // INDI properties panel state
  const [propertiesDeviceId, setPropertiesDeviceId] = useState<string | null>(null)
  const openProperties = useCallback((id: string) => {
    setPropertiesDeviceId((prev) => (prev === id ? null : id))
  }, [])

  const camera = deviceId
    ? (connectedDevices.find((d) => d.device_id === deviceId && d.kind === 'camera') ?? null)
    : null

  // Find focuser: prefer companion of camera, else first connected
  const focuser = camera
    ? (connectedDevices.find((d) => d.kind === 'focuser' && camera.companions.includes(d.device_id))
      ?? connectedDevices.find((d) => d.kind === 'focuser') ?? null)
    : null

  // Find filter wheel: prefer companion of camera, else first connected
  const filterWheel = camera
    ? (connectedDevices.find((d) => d.kind === 'filter_wheel' && camera.companions.includes(d.device_id))
      ?? connectedDevices.find((d) => d.kind === 'filter_wheel') ?? null)
    : null

  return (
    <>
    <div className="flex h-full">
      {/* Image viewer */}
      <div className="flex-1 flex flex-col min-w-0">
        <ImageViewer deviceId={deviceId} histoAuto={histoAuto} />
        <EventLog />
      </div>

      {/* Right sidebar */}
      <aside className="w-64 shrink-0 border-l border-surface-border overflow-y-auto bg-surface-raised py-1">
        {camera === null ? (
          <div className="p-4 text-xs text-slate-500">No camera connected.</div>
        ) : (
          <>
            <CameraPanel
              key={camera.device_id}
              deviceId={camera.device_id}
              name={camera.driver_name ?? camera.device_id}
              onSettings={openProperties}
              onHistoAutoChange={setHistoAuto}
            />
            {focuser && (
              <FocuserPanel key={focuser.device_id} deviceId={focuser.device_id} onSettings={openProperties} />
            )}
            {filterWheel && (
              <FilterWheelPanel key={filterWheel.device_id} deviceId={filterWheel.device_id} onSettings={openProperties} />
            )}
          </>
        )}
      </aside>
    </div>
    {propertiesDeviceId && (
      <DevicePropertiesPanel
        deviceId={propertiesDeviceId}
        onClose={() => setPropertiesDeviceId(null)}
      />
    )}
    </>
  )
}
