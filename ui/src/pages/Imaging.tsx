import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Camera, ChevronDown, ChevronUp, Crosshair, Play, Settings, Square, StopCircle, Thermometer,
} from 'lucide-react'
import { api } from '@/api/client'
import { useStore } from '@/store'
import type { CameraStatus, DitherConfig, FilterWheelStatus, FrameType } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { DevicePropertiesPanel } from '@/components/DevicePropertiesPanel'

// ── localStorage persistence ──────────────────────────────────────────────────

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
    <div className="border-b border-surface-border p-4">
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
  options, value, onChange, label,
}: { options: T[]; value: T; onChange: (v: T) => void; label: string }) {
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
            {o}
          </button>
        ))}
      </div>
    </div>
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

// ── Image Viewer ──────────────────────────────────────────────────────────────

function ImageViewer({ histoAuto }: { histoAuto: boolean }) {
  const image = useStore((s) => s.latestImage)
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
          <div className="absolute bottom-2 left-2 text-xs text-slate-400 bg-black/60 px-2 py-1 rounded">
            {image!.deviceId} · {image!.width}×{image!.height} · {image!.duration}s
          </div>
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
  deviceId, onSettings, histoAuto, onHistoAuto,
}: {
  deviceId: string
  onSettings: (id: string) => void
  histoAuto: boolean
  onHistoAuto: (v: boolean) => void
}) {
  const imagerBusy = useStore((s) => s.imagerBusy)
  const busy = imagerBusy[deviceId] ?? false

  // Persisted settings
  const [duration, setDuration] = useLocalStorage('imaging.duration', 5)
  const [gain, setGain] = useLocalStorage('imaging.gain', 0)
  const [binning, setBinning] = useLocalStorage<number>('imaging.binning', 1)
  const [frameType, setFrameType] = useLocalStorage<FrameType>('imaging.frameType', 'light')
  const [saveSubs, setSaveSubs] = useLocalStorage('imaging.saveSubs', true)

  const [gainMin, setGainMin] = useState(0)
  const [gainMax, setGainMax] = useState(65535)
  const [gainStep, setGainStep] = useState(1)
  const [looping, setLooping] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Dither settings (persisted)
  const [ditherFrames, setDitherFrames] = useLocalStorage<string>('imaging.ditherFrames', '')
  const [ditherMinutes, setDitherMinutes] = useLocalStorage<string>('imaging.ditherMinutes', '')

  // Camera hardware status (temperature, cooler)
  const [cameraStatus, setCameraStatus] = useState<CameraStatus | null>(null)
  const [targetTemp, setTargetTemp] = useLocalStorage<string>('imaging.targetTemp', '')

  useEffect(() => {
    if (!deviceId) return
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
    const frames = parseInt(ditherFrames)
    const minutes = parseFloat(ditherMinutes)
    if (!isNaN(frames) && frames > 0) return { every_frames: frames }
    if (!isNaN(minutes) && minutes > 0) return { every_minutes: minutes }
    return undefined
  }

  const expose = async () => {
    setError(null)
    try {
      await api.imager.expose(deviceId, { duration, gain, binning, frame_type: frameType, save: saveSubs })
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
          duration, gain, binning, frame_type: frameType, save: saveSubs,
          dither: buildDitherConfig() ?? null,
        })
        setLooping(true)
      }
    } catch (e) { setError((e as Error).message) }
  }

  const setCooler = async (enabled: boolean) => {
    const temp = parseFloat(targetTemp)
    try {
      await api.imager.setCooler(deviceId, enabled, !isNaN(temp) ? temp : undefined)
      setCameraStatus((s) => s ? { ...s, cooler_on: enabled } : s)
    } catch (e) { setError((e as Error).message) }
  }

  const applyTemp = async () => {
    const temp = parseFloat(targetTemp)
    if (isNaN(temp)) return
    try {
      await api.imager.setCooler(deviceId, cameraStatus?.cooler_on ?? true, temp)
    } catch (e) { setError((e as Error).message) }
  }

  const hasCooler = cameraStatus?.temperature != null

  return (
    <Panel title="Camera" deviceId={deviceId} onSettings={onSettings}>
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
                  value={targetTemp}
                  onChange={(e) => setTargetTemp(e.target.value)}
                  className="flex-1 text-xs"
                />
                <Button size="sm" variant="outline" onClick={applyTemp} disabled={!targetTemp}>Set</Button>
              </div>
            )}
          </div>
        )}

        {/* Frame type */}
        <PillGroup options={FRAME_TYPES} value={frameType} onChange={setFrameType} label="Frame type" />

        {/* Duration stepper */}
        <DurationStepper value={duration} onChange={setDuration} />

        {/* Gain */}
        <div className="flex flex-col gap-1">
          <div className="flex items-center justify-between">
            <span className="text-xs text-slate-400">Gain</span>
            <span className="text-xs text-slate-600">{gainMin}–{gainMax}</span>
          </div>
          <Input
            type="number" min={gainMin} max={gainMax} step={gainStep} value={gain}
            onChange={(e) => setGain(Math.max(gainMin, Math.min(gainMax, parseInt(e.target.value) || 0)))}
          />
        </div>

        {/* Binning */}
        <div className="flex flex-col gap-1">
          <span className="text-xs text-slate-400">Binning</span>
          <div className="flex gap-1">
            {BINNINGS.map((b) => (
              <button key={b} type="button" onClick={() => setBinning(b)}
                className={`px-2 py-0.5 text-xs rounded border transition-colors
                  ${binning === b ? 'border-accent text-accent bg-accent/10' : 'border-surface-border text-slate-400 hover:border-slate-500 hover:text-slate-300'}`}>
                {b}×{b}
              </button>
            ))}
          </div>
        </div>

        {/* Save subs + histogram toggle */}
        <div className="flex items-center justify-between">
          <label className="flex items-center gap-2 cursor-pointer select-none">
            <input type="checkbox" checked={saveSubs} onChange={(e) => setSaveSubs(e.target.checked)} className="accent-accent" />
            <span className="text-xs text-slate-300">Save subs</span>
          </label>
          <button
            onClick={() => onHistoAuto(!histoAuto)}
            title="Toggle histogram stretch"
            className={`text-xs px-2 py-0.5 rounded border transition-colors ${
              histoAuto
                ? 'border-accent text-accent bg-accent/10'
                : 'border-surface-border text-slate-500'
            }`}
          >
            {histoAuto ? 'Auto' : 'Linear'}
          </button>
        </div>

        {/* Guiding / dither */}
        <div className="border-t border-surface-border pt-2 flex flex-col gap-2">
          <div className="flex items-center gap-1.5">
            <Crosshair size={10} className="text-slate-500" />
            <span className="text-xs text-slate-500 uppercase tracking-wider">Guiding</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-400 shrink-0">Dither every</span>
            <Input
              type="number" min="1" step="1" placeholder="—"
              value={ditherFrames}
              onChange={(e) => { setDitherFrames(e.target.value); if (e.target.value) setDitherMinutes('') }}
              className="w-14 text-xs text-center"
            />
            <span className="text-xs text-slate-400 shrink-0">frames</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-400 shrink-0">Dither every</span>
            <Input
              type="number" min="0.1" step="0.5" placeholder="—"
              value={ditherMinutes}
              onChange={(e) => { setDitherMinutes(e.target.value); if (e.target.value) setDitherFrames('') }}
              className="w-14 text-xs text-center"
            />
            <span className="text-xs text-slate-400 shrink-0">minutes</span>
          </div>
        </div>

        {/* Actions */}
        <div className="flex gap-2">
          <Button size="sm" onClick={expose} disabled={busy}>
            <Camera size={12} className="mr-1" /> Expose
          </Button>
          <Button size="sm" variant={looping ? 'danger' : 'outline'} onClick={toggleLoop} disabled={busy && !looping}>
            {looping ? <><Square size={12} className="mr-1" /> Stop</> : <><Play size={12} className="mr-1" /> Loop</>}
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
  const connectedDevices = useStore((s) => s.connectedDevices)

  // Persisted histogram mode
  const [histoAuto, setHistoAuto] = useLocalStorage('imaging.histoAuto', true)

  // INDI properties panel state
  const [propertiesDeviceId, setPropertiesDeviceId] = useState<string | null>(null)
  const openProperties = useCallback((id: string) => {
    setPropertiesDeviceId((prev) => (prev === id ? null : id))
  }, [])

  // Resolve devices — camera is the anchor
  const camera = connectedDevices.find((d) => d.kind === 'camera') ?? null

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
        <ImageViewer histoAuto={histoAuto} />
        <EventLog />
      </div>

      {/* Right sidebar */}
      <aside className="w-64 shrink-0 border-l border-surface-border overflow-y-auto bg-surface-raised">
        {camera === null ? (
          <div className="p-4 text-xs text-slate-500">No camera connected.</div>
        ) : (
          <>
            <CameraPanel
              deviceId={camera.device_id}
              onSettings={openProperties}
              histoAuto={histoAuto}
              onHistoAuto={setHistoAuto}
            />
            {focuser && (
              <FocuserPanel
                deviceId={focuser.device_id}
                onSettings={openProperties}
              />
            )}
            {filterWheel && (
              <FilterWheelPanel
                deviceId={filterWheel.device_id}
                onSettings={openProperties}
              />
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
