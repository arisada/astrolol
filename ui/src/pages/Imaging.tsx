import { useEffect, useState } from 'react'
import { Square, Play, Camera, StopCircle, ChevronUp, ChevronDown } from 'lucide-react'
import { api } from '@/api/client'
import { useStore } from '@/store'
import type { FrameType } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

// ── Exposure duration steps ────────────────────────────────────────────────
// Curated astrophotography exposure times. Sub-second values use common
// fractions; longer values follow natural imaging increments.

const EXPOSURE_STEPS = [
  // Sub-second
  0.001, 0.002, 0.003, 0.004, 0.005, 0.008,
  0.01, 0.013, 0.015, 0.02, 0.025, 0.033, 0.04, 0.05,
  0.067, 0.08, 0.1, 0.125, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5,
  0.6, 0.8,
  // Seconds
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

// ── Image Viewer ──────────────────────────────────────────────────────────────

function ImageViewer() {
  const image = useStore((s) => s.latestImage)

  return (
    <div className="flex-1 bg-black flex items-center justify-center relative min-h-0">
      {image ? (
        <>
          <img
            src={image.previewUrl}
            alt="Latest exposure"
            className="max-w-full max-h-full object-contain"
          />
          <div className="absolute bottom-2 left-2 text-xs text-slate-400 bg-black/60 px-2 py-1 rounded">
            {image.deviceId} · {image.width}×{image.height} · {image.duration}s
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
  // Find the index of the nearest step to the current value
  const idx = EXPOSURE_STEPS.reduce(
    (best, v, i) => Math.abs(v - value) < Math.abs(EXPOSURE_STEPS[best] - value) ? i : best,
    0,
  )

  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs text-slate-400">Duration</span>
      <div className="flex items-center gap-1">
        <Button
          size="icon" variant="outline"
          disabled={idx === 0}
          onClick={() => onChange(EXPOSURE_STEPS[idx - 1])}
          title="Shorter"
        >
          <ChevronDown size={14} />
        </Button>
        <span className="flex-1 text-center text-xs font-mono text-slate-200 bg-surface-overlay border border-surface-border rounded px-2 py-1.5 min-w-[5rem]">
          {fmtDuration(value)}
        </span>
        <Button
          size="icon" variant="outline"
          disabled={idx === EXPOSURE_STEPS.length - 1}
          onClick={() => onChange(EXPOSURE_STEPS[idx + 1])}
          title="Longer"
        >
          <ChevronUp size={14} />
        </Button>
      </div>
    </div>
  )
}

function CameraPanel() {
  const devices = useStore((s) => s.connectedDevices.filter((d) => d.kind === 'camera'))
  const imagerBusy = useStore((s) => s.imagerBusy)
  const [deviceId, setDeviceId] = useState('')

  // Exposure settings
  const [duration, setDuration] = useState(EXPOSURE_STEPS[EXPOSURE_STEPS.indexOf(5)])
  const [gain, setGain] = useState(0)
  const [gainMin, setGainMin] = useState(0)
  const [gainMax, setGainMax] = useState(65535)
  const [gainStep, setGainStep] = useState(1)
  const [binning, setBinning] = useState(1)
  const [frameType, setFrameType] = useState<FrameType>('light')
  const [looping, setLooping] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const activeId = deviceId || devices[0]?.device_id || ''
  const busy = imagerBusy[activeId] ?? false

  // Fetch gain constraints from INDI properties whenever the active camera changes.
  // Fails silently for non-INDI cameras (fake adapter, no INDI client, etc.).
  useEffect(() => {
    if (!activeId) return
    api.devices.properties(activeId)
      .then((props) => {
        for (const p of props) {
          if (p.type !== 'number') continue
          const w = p.widgets.find(
            (w) => w.name?.toLowerCase() === 'gain' || w.label?.toLowerCase() === 'gain',
          )
          if (w) {
            if (w.min != null) setGainMin(w.min as number)
            if (w.max != null) setGainMax(w.max as number)
            if (w.step != null && (w.step as number) > 0) setGainStep(w.step as number)
            if (typeof w.value === 'number') setGain(w.value)
            break
          }
        }
      })
      .catch(() => { /* not an INDI device or client not running */ })
  }, [activeId])

  const expose = async () => {
    if (!activeId) return
    setError(null)
    try {
      await api.imager.expose(activeId, { duration, gain, binning, frame_type: frameType })
    } catch (e) { setError((e as Error).message) }
  }

  const toggleLoop = async () => {
    if (!activeId) return
    setError(null)
    try {
      if (looping) {
        await api.imager.stopLoop(activeId)
        setLooping(false)
      } else {
        await api.imager.startLoop(activeId, { duration, gain, binning, frame_type: frameType })
        setLooping(true)
      }
    } catch (e) { setError((e as Error).message) }
  }

  return (
    <Panel title="Camera">
      {devices.length === 0 ? (
        <p className="text-xs text-slate-500">No camera connected.</p>
      ) : (
        <div className="flex flex-col gap-3">
          {devices.length > 1 && (
            <select
              className="rounded bg-surface-overlay border border-surface-border px-2 py-1 text-xs text-slate-200 focus:outline-none"
              value={activeId}
              onChange={(e) => setDeviceId(e.target.value)}
            >
              {devices.map((d) => <option key={d.device_id} value={d.device_id}>{d.device_id}</option>)}
            </select>
          )}

          {/* Frame type */}
          <PillGroup
            options={FRAME_TYPES}
            value={frameType}
            onChange={setFrameType}
            label="Frame type"
          />

          {/* Duration stepper */}
          <DurationStepper value={duration} onChange={setDuration} />

          {/* Gain */}
          <div className="flex flex-col gap-1">
            <div className="flex items-center justify-between">
              <span className="text-xs text-slate-400">Gain</span>
              <span className="text-xs text-slate-600">{gainMin}–{gainMax}</span>
            </div>
            <Input
              type="number"
              min={gainMin}
              max={gainMax}
              step={gainStep}
              value={gain}
              onChange={(e) => setGain(Math.max(gainMin, Math.min(gainMax, parseInt(e.target.value) || 0)))}
            />
          </div>

          {/* Binning */}
          <div className="flex flex-col gap-1">
            <span className="text-xs text-slate-400">Binning</span>
            <div className="flex gap-1">
              {BINNINGS.map((b) => (
                <button
                  key={b}
                  type="button"
                  onClick={() => setBinning(b)}
                  className={`px-2 py-0.5 text-xs rounded border transition-colors
                    ${binning === b
                      ? 'border-accent text-accent bg-accent/10'
                      : 'border-surface-border text-slate-400 hover:border-slate-500 hover:text-slate-300'
                    }`}
                >
                  {b}×{b}
                </button>
              ))}
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
      )}
    </Panel>
  )
}

// ── Focuser Panel ─────────────────────────────────────────────────────────────

function FocuserPanel() {
  const devices = useStore((s) => s.connectedDevices.filter((d) => d.kind === 'focuser'))
  const focuserStatuses = useStore((s) => s.focuserStatuses)
  const [target, setTarget] = useState('')
  const [step, setStep] = useState('100')
  const [error, setError] = useState<string | null>(null)

  const activeId = devices[0]?.device_id ?? ''
  const position = focuserStatuses[activeId]?.position

  const act = async (fn: () => Promise<unknown>) => {
    setError(null)
    try { await fn() } catch (e) { setError((e as Error).message) }
  }

  return (
    <Panel title="Focuser">
      {devices.length === 0 ? (
        <p className="text-xs text-slate-500">No focuser connected.</p>
      ) : (
        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-400">Position</span>
            <span className="text-sm font-mono text-slate-200">{position ?? '—'}</span>
          </div>

          {/* Relative nudge */}
          <div className="flex items-center gap-2">
            <Button size="icon" variant="outline" onClick={() => act(() => api.focuser.moveBy(activeId, -parseInt(step)))} title="Move in">
              <ChevronDown size={14} />
            </Button>
            <Input
              className="w-20 text-center"
              type="number"
              min="1"
              value={step}
              onChange={(e) => setStep(e.target.value)}
            />
            <Button size="icon" variant="outline" onClick={() => act(() => api.focuser.moveBy(activeId, parseInt(step)))} title="Move out">
              <ChevronUp size={14} />
            </Button>
            <span className="text-xs text-slate-500">steps</span>
          </div>

          {/* Absolute move */}
          <div className="flex gap-2">
            <Input
              type="number"
              min="0"
              placeholder="Absolute position"
              value={target}
              onChange={(e) => setTarget(e.target.value)}
            />
            <Button size="sm" onClick={() => act(() => api.focuser.moveTo(activeId, parseInt(target)))} disabled={!target}>
              Go
            </Button>
          </div>

          <Button size="sm" variant="danger" onClick={() => act(() => api.focuser.halt(activeId))}>
            <StopCircle size={12} className="mr-1" /> Halt
          </Button>
          {error && <p className="text-xs text-status-error">{error}</p>}
        </div>
      )}
    </Panel>
  )
}

// ── Event Log ─────────────────────────────────────────────────────────────────

function EventLog() {
  const log = useStore((s) => s.log)
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

// ── Helpers ───────────────────────────────────────────────────────────────────

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="border-b border-surface-border p-4">
      <h3 className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-3">{title}</h3>
      {children}
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export function Imaging() {
  return (
    <div className="flex h-full">
      {/* Image viewer — takes all remaining space */}
      <div className="flex-1 flex flex-col min-w-0">
        <ImageViewer />
        <EventLog />
      </div>

      {/* Right sidebar — device controls */}
      <aside className="w-64 shrink-0 border-l border-surface-border overflow-y-auto bg-surface-raised">
        <CameraPanel />
        <FocuserPanel />
      </aside>
    </div>
  )
}
