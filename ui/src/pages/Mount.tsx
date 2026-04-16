import { useCallback, useEffect, useRef, useState } from 'react'
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Crosshair, RefreshCw, RotateCw, Settings, StopCircle } from 'lucide-react'
import { api } from '@/api/client'
import { useStore } from '@/store'
import type { MountStatus, TrackingMode } from '@/api/types'
import { Button } from '@/components/ui/button'
import { DmsInput } from '@/components/ui/dms-input'
import { StateBadge } from '@/components/ui/badge'
import { DevicePropertiesPanel } from '@/components/DevicePropertiesPanel'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MOVE_RATES = [
  { label: 'Guide',   rate: 'guide'     },
  { label: 'Center',  rate: 'centering' },
  { label: 'Find',    rate: 'find'      },
  { label: 'Max',     rate: 'max'       },
] as const

const TRACKING_MODES: { label: string; mode: TrackingMode }[] = [
  { label: 'Sidereal', mode: 'sidereal' },
  { label: 'Lunar',    mode: 'lunar'    },
  { label: 'Solar',    mode: 'solar'    },
]

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

function fmtHA(ha: number | null | undefined): string {
  if (ha == null) return '—'
  const sign = ha >= 0 ? '+' : '−'
  const abs = Math.abs(ha)
  const h = Math.floor(abs)
  const m = Math.floor((abs - h) * 60)
  if (h === 0) return `${sign}${m}m`
  return `${sign}${h}h ${String(m).padStart(2, '0')}m`
}

function fmtMeridianDistance(ha: number): string {
  const abs = Math.abs(ha)
  const h = Math.floor(abs)
  const m = Math.floor((abs - h) * 60)
  const parts = h > 0 ? `${h}h ${m}m` : `${m}m`
  return ha < 0 ? `${parts} to meridian` : `${parts} past meridian`
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
  const [showIndiPanel, setShowIndiPanel] = useState(false)

  const [slewRa, setSlewRa] = useState(0)
  const [slewDec, setSlewDec] = useState(0)
  const slewEdited = useRef(false)

  const [rateIdx, setRateIdx] = useState(1)
  const [trackingMode, setTrackingMode] = useState<TrackingMode>('sidereal')
  const [error, setError] = useState<string | null>(null)
  const movingRef = useRef(false)

  useEffect(() => {
    let alive = true
    const poll = async () => {
      try {
        const s = await api.mount.status(deviceId)
        if (alive) {
          setStatus(s)
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

  const handleMoveStart = useCallback(async (direction: string) => {
    if (movingRef.current) return
    movingRef.current = true
    await act(() => api.mount.startMove(deviceId, direction, MOVE_RATES[rateIdx].rate))
  }, [deviceId, rateIdx, act])

  const handleMoveStop = useCallback(async () => {
    if (!movingRef.current) return
    movingRef.current = false
    await act(() => api.mount.stopMove(deviceId))
  }, [deviceId, act])

  const isTracking = status?.is_tracking ?? false
  const isParked   = status?.is_parked   ?? false
  const isSlewing  = status?.is_slewing  ?? false
  const ha         = status?.hour_angle ?? null
  const lst        = status?.lst ?? null
  // Flip is useful once the mount has passed the meridian (HA > 0) and within 2h past it.
  // Before the meridian (HA < 0) a flip would point the OTA through the mount.
  const canFlip    = ha != null && ha > 0 && ha <= 2.0 && !isParked && !isSlewing

  // Common props for d-pad buttons (hold to move)
  const dpadBtn = (dir: string, title: string) => ({
    onMouseDown: () => handleMoveStart(dir),
    onMouseUp: handleMoveStop,
    onMouseLeave: handleMoveStop,
    onTouchStart: (e: React.TouchEvent) => { e.preventDefault(); handleMoveStart(dir) },
    onTouchEnd: handleMoveStop,
    disabled: !status || isParked,
    title,
  })

  return (
    <div className="h-full overflow-y-auto p-4">
      <div className="max-w-md mx-auto flex flex-col gap-4">

        {/* Header */}
        <div className="flex items-center justify-between">
          <h2 className="text-slate-200 font-semibold truncate">{deviceId}</h2>
          <div className="flex items-center gap-2">
            {isSlewing && (
              <span className="text-xs text-yellow-400 animate-pulse">Slewing…</span>
            )}
            {status && <StateBadge state={status.state} />}
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setShowIndiPanel((v) => !v)}
              title="INDI properties"
              className={showIndiPanel ? 'text-accent' : ''}
            >
              <Settings size={15} />
            </Button>
          </div>
        </div>
        {showIndiPanel && (
          <DevicePropertiesPanel deviceId={deviceId} onClose={() => setShowIndiPanel(false)} />
        )}

        {/* Live position */}
        <Section title="Position (JNOW)">
          <div className="grid grid-cols-2 gap-x-8 gap-y-1 font-mono text-sm">
            <span className="text-slate-500 text-xs">RA</span>
            <span className="text-slate-500 text-xs">Dec</span>
            <span className="text-slate-200">{fmtRA(status?.ra)}</span>
            <span className="text-slate-200">{fmtDec(status?.dec)}</span>
            <span className="text-slate-500 text-xs mt-1">Alt</span>
            <span className="text-slate-500 text-xs mt-1">Az</span>
            <span className="text-slate-300">{status?.alt != null ? `${status.alt.toFixed(1)}°` : '—'}</span>
            <span className="text-slate-300">{status?.az  != null ? `${status.az.toFixed(1)}°`  : '—'}</span>
            <span className="text-slate-500 text-xs mt-1">HA</span>
            <span className="text-slate-500 text-xs mt-1">LST</span>
            <span className="text-slate-300">{fmtHA(ha)}</span>
            <span className="text-slate-300">{lst != null ? fmtRA(lst) : '—'}</span>
            <span className="text-slate-500 text-xs mt-1">Pier</span>
            <span className="text-slate-500 text-xs mt-1" />
            <span className="text-slate-300">{status?.pier_side ?? '—'}</span>
            <span />
          </div>
        </Section>

        {/* Slew */}
        <Section title="Slew to (JNOW)">
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
          <div className="flex gap-2 items-center flex-wrap">
            <Button size="sm" onClick={() => act(() => api.mount.slew(deviceId, slewRa, slewDec))}>
              <Crosshair size={12} className="mr-1" /> Slew
            </Button>
            <Button size="sm" variant="outline" onClick={() => act(() => api.mount.sync(deviceId, slewRa, slewDec))}>
              <RotateCw size={12} className="mr-1" /> Sync
            </Button>
            <Button size="sm" variant="outline" onClick={() => act(() => api.mount.stop(deviceId))}>
              <StopCircle size={12} className="mr-1" /> Stop
            </Button>
            {slewEdited.current && (
              <button
                type="button"
                className="ml-auto text-xs text-slate-500 hover:text-slate-300 transition-colors"
                onClick={() => {
                  slewEdited.current = false
                  if (status?.ra != null && status?.dec != null) {
                    setSlewRa(status.ra)
                    setSlewDec(status.dec)
                  }
                }}
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
              onChange={() => act(() => api.mount.setTracking(deviceId, !isTracking, isTracking ? undefined : trackingMode))}
            />
            <span className="text-sm text-slate-300 w-6">{isTracking ? 'On' : 'Off'}</span>
            <select
              disabled={isParked}
              className="ml-auto rounded bg-surface-overlay border border-surface-border px-2 py-1 text-xs text-slate-200 focus:outline-none disabled:opacity-40 disabled:cursor-not-allowed"
              value={trackingMode}
              onChange={(e) => {
                const m = e.target.value as TrackingMode
                setTrackingMode(m)
                act(() => api.mount.setTracking(deviceId, true, m))
              }}
            >
              {TRACKING_MODES.map(({ label, mode }) => <option key={mode} value={mode}>{label}</option>)}
            </select>
          </div>
          {isParked
            ? <p className="text-xs text-slate-500">Unpark the mount to enable tracking.</p>
            : <p className="text-xs text-slate-600">Lunar / Solar rates require firmware support.</p>
          }
        </Section>

        {/* Park */}
        <Section title="Park">
          <div className="flex items-center gap-3 flex-wrap">
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
            <Button
              size="sm"
              variant="ghost"
              disabled={isParked}
              onClick={() => act(() => api.mount.setParkPosition(deviceId))}
              title="Set current position as the park position"
            >
              Set as park position
            </Button>
            {isParked && <span className="text-xs text-slate-500">Mount is parked.</span>}
          </div>
        </Section>

        {/* Meridian */}
        <Section title="Meridian">
          {ha != null && (
            <p className="text-xs text-slate-500">{fmtMeridianDistance(ha)}</p>
          )}
          <div className="flex items-center gap-3">
            <Button
              size="sm"
              variant="outline"
              disabled={!canFlip}
              onClick={() => act(() => api.mount.meridianFlip(deviceId))}
              title={
                canFlip            ? 'Perform meridian flip' :
                ha == null         ? 'Hour angle unknown' :
                ha <= 0            ? 'Mount has not crossed the meridian yet' :
                                     'More than 2 h past meridian — slew to target first'
              }
            >
              <RefreshCw size={12} className="mr-1.5" /> Meridian Flip
            </Button>
            {ha != null && !canFlip && ha <= 0 && (
              <span className="text-xs text-slate-600">Waiting for meridian crossing</span>
            )}
            {ha != null && !canFlip && ha > 2.0 && (
              <span className="text-xs text-yellow-700">Slew to target before flipping</span>
            )}
          </div>
        </Section>

        {/* Nudge */}
        <Section title="Nudge">
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500">Rate</span>
            <select
              className="rounded bg-surface-overlay border border-surface-border px-2 py-1 text-xs text-slate-200 focus:outline-none"
              value={rateIdx}
              onChange={(e) => setRateIdx(parseInt(e.target.value))}
            >
              {MOVE_RATES.map((s, i) => <option key={s.label} value={i}>{s.label}</option>)}
            </select>
            <span className="text-xs text-slate-600 ml-2">Hold to move, release to stop</span>
          </div>
          {/* D-pad */}
          <div className="flex flex-col items-center gap-1 self-center select-none">
            <Button size="icon" variant="outline" {...dpadBtn('N', 'North')} >
              <ArrowUp size={16} />
            </Button>
            <div className="flex gap-8">
              <Button size="icon" variant="outline" {...dpadBtn('W', 'West')} >
                <ArrowLeft size={16} />
              </Button>
              <Button size="icon" variant="outline" {...dpadBtn('E', 'East')} >
                <ArrowRight size={16} />
              </Button>
            </div>
            <Button size="icon" variant="outline" {...dpadBtn('S', 'South')} >
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

  return <MountControls deviceId={mounts[0].device_id} />
}
