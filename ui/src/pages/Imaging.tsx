import { useState } from 'react'
import { Square, Play, Camera, StopCircle, MoveRight, ChevronUp, ChevronDown } from 'lucide-react'
import { api } from '@/api/client'
import { useStore } from '@/store'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { StateBadge } from '@/components/ui/badge'

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

function CameraPanel() {
  const devices = useStore((s) => s.connectedDevices.filter((d) => d.kind === 'camera'))
  const imagerBusy = useStore((s) => s.imagerBusy)
  const [deviceId, setDeviceId] = useState('')
  const [duration, setDuration] = useState('5')
  const [gain, setGain] = useState('0')
  const [looping, setLooping] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const activeId = deviceId || devices[0]?.device_id || ''
  const busy = imagerBusy[activeId] ?? false

  const expose = async () => {
    if (!activeId) return
    setError(null)
    try {
      await api.imager.expose(activeId, { duration: parseFloat(duration), gain: parseInt(gain) })
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
        await api.imager.startLoop(activeId, { duration: parseFloat(duration), gain: parseInt(gain) })
        setLooping(true)
      }
    } catch (e) { setError((e as Error).message) }
  }

  return (
    <Panel title="Camera">
      {devices.length === 0 ? (
        <p className="text-xs text-slate-500">No camera connected.</p>
      ) : (
        <div className="flex flex-col gap-2">
          {devices.length > 1 && (
            <select
              className="rounded bg-surface-overlay border border-surface-border px-2 py-1 text-xs text-slate-200 focus:outline-none"
              value={activeId}
              onChange={(e) => setDeviceId(e.target.value)}
            >
              {devices.map((d) => <option key={d.device_id} value={d.device_id}>{d.device_id}</option>)}
            </select>
          )}
          <div className="grid grid-cols-2 gap-2">
            <LabeledInput label="Duration (s)" value={duration} onChange={setDuration} type="number" min="0.001" step="0.5" />
            <LabeledInput label="Gain" value={gain} onChange={setGain} type="number" min="0" />
          </div>
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

// ── Mount Panel ───────────────────────────────────────────────────────────────

function MountPanel() {
  const devices = useStore((s) => s.connectedDevices.filter((d) => d.kind === 'mount'))
  const [ra, setRa] = useState('')
  const [dec, setDec] = useState('')
  const [error, setError] = useState<string | null>(null)

  const activeId = devices[0]?.device_id ?? ''

  const act = async (fn: () => Promise<unknown>) => {
    setError(null)
    try { await fn() } catch (e) { setError((e as Error).message) }
  }

  return (
    <Panel title="Mount">
      {devices.length === 0 ? (
        <p className="text-xs text-slate-500">No mount connected.</p>
      ) : (
        <div className="flex flex-col gap-2">
          <StateBadge state={devices[0].state} />
          <div className="grid grid-cols-2 gap-2">
            <LabeledInput label="RA (h)" value={ra} onChange={setRa} type="number" min="0" max="24" step="0.001" placeholder="0–24" />
            <LabeledInput label="Dec (°)" value={dec} onChange={setDec} type="number" min="-90" max="90" step="0.01" placeholder="−90–90" />
          </div>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" onClick={() => act(() => api.mount.slew(activeId, parseFloat(ra), parseFloat(dec)))} disabled={!ra || !dec}>
              <MoveRight size={12} className="mr-1" /> Slew
            </Button>
            <Button size="sm" variant="outline" onClick={() => act(() => api.mount.stop(activeId))}>
              <StopCircle size={12} className="mr-1" /> Stop
            </Button>
            <Button size="sm" variant="outline" onClick={() => act(() => api.mount.park(activeId))}>Park</Button>
            <Button size="sm" variant="outline" onClick={() => act(() => api.mount.unpark(activeId))}>Unpark</Button>
          </div>
          <div className="flex gap-2">
            <Button size="sm" variant="outline" onClick={() => act(() => api.mount.setTracking(activeId, true))}>Track on</Button>
            <Button size="sm" variant="outline" onClick={() => act(() => api.mount.setTracking(activeId, false))}>Track off</Button>
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

function LabeledInput({
  label, value, onChange, ...rest
}: { label: string; value: string; onChange: (v: string) => void } & Omit<React.InputHTMLAttributes<HTMLInputElement>, 'value' | 'onChange'>) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs text-slate-400">{label}</label>
      <Input value={value} onChange={(e) => onChange(e.target.value)} {...rest} />
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
        <MountPanel />
        <FocuserPanel />
      </aside>
    </div>
  )
}
