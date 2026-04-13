import { useCallback, useEffect, useRef, useState } from 'react'
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Crosshair, StopCircle } from 'lucide-react'
import { api } from '@/api/client'
import { useStore } from '@/store'
import type { MountStatus } from '@/api/types'
import { Button } from '@/components/ui/button'
import { DmsInput } from '@/components/ui/dms-input'
import { StateBadge } from '@/components/ui/badge'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

// Angular step sizes in degrees per nudge click.
// RA delta in hours = deg / 15 (independent of declination — good enough for manual nudge).
const SPEEDS = [
  { label: 'Guide', deg: 0.004  },  // ≈ 15 arcsec
  { label: '1×',   deg: 0.017  },  // ≈ 1 arcmin
  { label: '8×',   deg: 0.13   },  // ≈ 8 arcmin
  { label: '32×',  deg: 0.5    },  // ≈ 30 arcmin
] as const

const TRACKING_MODES = ['Sidereal', 'Lunar', 'Solar'] as const
type TrackingMode = (typeof TRACKING_MODES)[number]

// ---------------------------------------------------------------------------
// Pure formatting helpers
// ---------------------------------------------------------------------------

function fmtRA(h: number | null | undefined): string {
  if (h == null) return '—'
  const H = Math.floor(h)
  const mf = (h - H) * 60
  const M = Math.floor(mf)
  const S = ((mf - M) * 60).toFixed(1)
  return `${String(H).padStart(2, '0')}h ${String(M).padStart(2, '0')}m ${S.padStart(4, '0')}s`
}

function fmtDec(d: number | null | undefined): string {
  if (d == null) return '—'
  const sign = d < 0 ? '−' : '+'
  const abs = Math.abs(d)
  const deg = Math.floor(abs)
  const mf = (abs - deg) * 60
  const min = Math.floor(mf)
  const sec = Math.round((mf - min) * 60)
  return `${sign}${String(deg).padStart(2, '0')}° ${String(min).padStart(2, '0')}' ${String(sec).padStart(2, '0')}"`
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="border border-surface-border rounded-lg p-4 flex flex-col gap-3">
      <h3 className="text-xs font-medium text-slate-500 uppercase tracking-wider">{title}</h3>
      {children}
    </div>
  )
}

function ToggleSwitch({ checked, onChange, label, disabled }: {
  checked: boolean; onChange: () => void; label: string; disabled?: boolean
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={disabled ? undefined : onChange}
      disabled={disabled}
      className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors focus:outline-none
        disabled:opacity-40 disabled:cursor-not-allowed
        ${checked ? 'bg-accent' : 'bg-surface-border'} ${!disabled ? 'cursor-pointer' : ''}`}
      aria-label={label}
    >
      <span className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition-transform
        ${checked ? 'translate-x-[22px]' : 'translate-x-0.5'}`}
      />
    </button>
  )
}

// ---------------------------------------------------------------------------
// Main controls component (rendered when a mount is connected)
// ---------------------------------------------------------------------------

function MountControls({ deviceId }: { deviceId: string }) {
  const [status, setStatus] = useState<MountStatus | null>(null)

  // Slew target state (decimal hours for RA, decimal degrees for Dec).
  // Tracks the live position until the user manually edits a field.
  const [slewRa, setSlewRa] = useState(0)
  const [slewDec, setSlewDec] = useState(0)
  // Set to true on first user edit; cleared if the user explicitly resets to live position.
  const slewEdited = useRef(false)

  const [speedIdx, setSpeedIdx] = useState(1)
  const [trackingMode, setTrackingMode] = useState<TrackingMode>('Sidereal')
  const [error, setError] = useState<string | null>(null)

  // Poll mount status every 2 s
  useEffect(() => {
    let alive = true
    const poll = async () => {
      try {
        const s = await api.mount.status(deviceId)
        if (alive) {
          setStatus(s)
          // Keep slew fields in sync with live position until the user edits them
          if (!slewEdited.current && s.ra != null && s.dec != null) {
            setSlewRa(s.ra)
            setSlewDec(s.dec)
          }
        }
      } catch { /* ignore poll errors */ }
    }
    poll()
    const id = setInterval(poll, 2000)
    return () => { alive = false; clearInterval(id) }
  }, [deviceId])

  const act = useCallback(async (fn: () => Promise<unknown>) => {
    setError(null)
    try { await fn() } catch (e) { setError((e as Error).message) }
  }, [])

  // Apply a directional nudge by computing a new target RA/Dec from the live position.
  const nudge = useCallback(async (dRaSign: number, dDecSign: number) => {
    if (status?.ra == null || status?.dec == null) return
    const step = SPEEDS[speedIdx].deg
    const newRa = ((status.ra + (dRaSign * step) / 15) + 24) % 24
    const newDec = Math.max(-90, Math.min(90, status.dec + dDecSign * step))
    await act(() => api.mount.slew(deviceId, newRa, newDec))
  }, [status, speedIdx, deviceId, act])

  const isTracking = status?.is_tracking ?? false
  const isParked   = status?.is_parked   ?? false

  return (
    <div className="h-full overflow-y-auto p-4">
      <div className="max-w-md mx-auto flex flex-col gap-4">

        {/* Header */}
        <div className="flex items-center justify-between">
          <h2 className="text-slate-200 font-semibold truncate">{deviceId}</h2>
          {status && <StateBadge state={status.state} />}
        </div>

        {/* Live position */}
        <Section title="Position">
          <div className="grid grid-cols-2 gap-x-8 gap-y-1 font-mono text-sm">
            <span className="text-slate-500 text-xs">RA</span>
            <span className="text-slate-500 text-xs">Dec</span>
            <span className="text-slate-200">{fmtRA(status?.ra)}</span>
            <span className="text-slate-200">{fmtDec(status?.dec)}</span>
            <span className="text-slate-500 text-xs mt-1">Alt</span>
            <span className="text-slate-500 text-xs mt-1">Az</span>
            <span className="text-slate-400">{status?.alt != null ? `${status.alt.toFixed(1)}°` : '—'}</span>
            <span className="text-slate-400">{status?.az  != null ? `${status.az.toFixed(1)}°`  : '—'}</span>
          </div>
        </Section>

        {/* Slew */}
        <Section title="Slew to">
          <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-500 w-8 shrink-0">RA</span>
              <DmsInput value={slewRa} onChange={(v) => { slewEdited.current = true; setSlewRa(v) }} mode="ra" />
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-500 w-8 shrink-0">Dec</span>
              <DmsInput value={slewDec} onChange={(v) => { slewEdited.current = true; setSlewDec(v) }} mode="lat" />
            </div>
          </div>
          <div className="flex gap-2 items-center">
            <Button size="sm" onClick={() => act(() => api.mount.slew(deviceId, slewRa, slewDec))}>
              <Crosshair size={12} className="mr-1" /> Slew
            </Button>
            <Button size="sm" variant="outline" onClick={() => act(() => api.mount.stop(deviceId))}>
              <StopCircle size={12} className="mr-1" /> Stop
            </Button>
            {slewEdited.current && (
              <button
                type="button"
                className="ml-auto text-xs text-slate-500 hover:text-slate-300 transition-colors"
                onClick={() => { slewEdited.current = false; if (status?.ra != null && status?.dec != null) { setSlewRa(status.ra); setSlewDec(status.dec) } }}
              >
                ↺ live
              </button>
            )}
          </div>
        </Section>

        {/* Tracking */}
        <Section title="Tracking">
          <div className="flex items-center gap-3">
            <ToggleSwitch
              checked={isTracking}
              label="Toggle tracking"
              disabled={isParked}
              onChange={() => act(() => api.mount.setTracking(deviceId, !isTracking))}
            />
            <span className="text-sm text-slate-300 w-6">{isTracking ? 'On' : 'Off'}</span>
            <select
              disabled={isParked}
              className="ml-auto rounded bg-surface-overlay border border-surface-border px-2 py-1 text-xs text-slate-200 focus:outline-none disabled:opacity-40 disabled:cursor-not-allowed"
              value={trackingMode}
              onChange={(e) => {
                setTrackingMode(e.target.value as TrackingMode)
                // Selecting a mode implies tracking should be on
                if (!isTracking) act(() => api.mount.setTracking(deviceId, true))
              }}
            >
              {TRACKING_MODES.map((m) => <option key={m}>{m}</option>)}
            </select>
          </div>
          {isParked
            ? <p className="text-xs text-slate-500">Unpark the mount to enable tracking.</p>
            : <p className="text-xs text-slate-600">Lunar / Solar rates require firmware support.</p>
          }
        </Section>

        {/* Park */}
        <Section title="Park">
          <div className="flex items-center gap-3">
            <Button
              size="sm"
              variant={isParked ? 'default' : 'outline'}
              onClick={() => act(isParked
                ? () => api.mount.unpark(deviceId)
                : () => api.mount.park(deviceId)
              )}
            >
              {isParked ? 'Unpark' : 'Park'}
            </Button>
            {isParked && <span className="text-xs text-slate-500">Mount is parked.</span>}
          </div>
        </Section>

        {/* Nudge */}
        <Section title="Nudge">
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500">Speed</span>
            <select
              className="rounded bg-surface-overlay border border-surface-border px-2 py-1 text-xs text-slate-200 focus:outline-none"
              value={speedIdx}
              onChange={(e) => setSpeedIdx(parseInt(e.target.value))}
            >
              {SPEEDS.map((s, i) => <option key={s.label} value={i}>{s.label}</option>)}
            </select>
          </div>
          {/* D-pad */}
          <div className="flex flex-col items-center gap-1 self-center">
            <Button size="icon" variant="outline" onClick={() => nudge(0, 1)} disabled={!status} title="North">
              <ArrowUp size={16} />
            </Button>
            <div className="flex gap-8">
              <Button size="icon" variant="outline" onClick={() => nudge(-1, 0)} disabled={!status} title="West">
                <ArrowLeft size={16} />
              </Button>
              <Button size="icon" variant="outline" onClick={() => nudge(1, 0)} disabled={!status} title="East">
                <ArrowRight size={16} />
              </Button>
            </div>
            <Button size="icon" variant="outline" onClick={() => nudge(0, -1)} disabled={!status} title="South">
              <ArrowDown size={16} />
            </Button>
          </div>
        </Section>

        {error && <p className="text-xs text-status-error">{error}</p>}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Page entry point
// ---------------------------------------------------------------------------

export function Mount() {
  const mounts = useStore((s) => s.connectedDevices.filter((d) => d.kind === 'mount'))

  if (mounts.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-2 text-slate-600">
        <span className="text-sm">No mount connected.</span>
        <span className="text-xs">Connect a mount in Equipment or activate a profile.</span>
      </div>
    )
  }

  // If multiple mounts are connected, use the first one.
  // (Multi-mount support can be added later with a device selector.)
  return <MountControls deviceId={mounts[0].device_id} />
}
