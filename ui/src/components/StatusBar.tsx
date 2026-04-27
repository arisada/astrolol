/**
 * Global status bar — always visible at the top of every page.
 * Shows live status chips for connected mounts, imagers, focusers,
 * filter wheels, PHD2 guiding, and active plate solves.
 */
import { useEffect, useState } from 'react'
import { Wifi, WifiOff } from 'lucide-react'
import { useStore } from '@/store'
import { getAllPluginEntries } from '@/plugin-registry'
import type { ConnectedDevice } from '@/api/types'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function shortName(d: ConnectedDevice): string {
  const name = d.driver_name ?? d.device_id
  return name.length > 22 ? name.slice(0, 20) + '…' : name
}

function fmtSeconds(s: number): string {
  return s >= 10 ? `${s.toFixed(0)}s` : `${s.toFixed(1)}s`
}

// ---------------------------------------------------------------------------
// Countdown hook — updates every 200 ms while an exposure is running
// ---------------------------------------------------------------------------

function useCountdown(exposure: { startedAt: number; duration: number } | null | undefined) {
  const [remaining, setRemaining] = useState<number | null>(null)

  useEffect(() => {
    if (!exposure) { setRemaining(null); return }
    const update = () => {
      const elapsed = (Date.now() - exposure.startedAt) / 1000
      setRemaining(Math.max(0, exposure.duration - elapsed))
    }
    update()
    const id = setInterval(update, 200)
    return () => clearInterval(id)
  }, [exposure?.startedAt, exposure?.duration])   // eslint-disable-line react-hooks/exhaustive-deps

  return remaining
}

// ---------------------------------------------------------------------------
// Chip primitives
// ---------------------------------------------------------------------------

type ChipVariant = 'green' | 'amber' | 'red' | 'blue' | 'violet' | 'slate'

const chipClasses: Record<ChipVariant, string> = {
  green:  'bg-emerald-500/20 text-emerald-300 border-emerald-500/30',
  amber:  'bg-amber-500/20  text-amber-300  border-amber-500/30',
  red:    'bg-rose-500/20   text-rose-300   border-rose-500/30',
  blue:   'bg-sky-500/20    text-sky-300    border-sky-500/30',
  violet: 'bg-violet-500/20 text-violet-300 border-violet-500/30',
  slate:  'bg-slate-700/50  text-slate-400  border-slate-600/40',
}

function Chip({
  label,
  status,
  variant,
  pulse = false,
}: {
  label: string
  status: string
  variant: ChipVariant
  pulse?: boolean
}) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded border text-xs font-medium whitespace-nowrap
        ${chipClasses[variant]} ${pulse ? 'animate-pulse' : ''}`}
    >
      <span className="text-slate-400 truncate max-w-[10rem]">{label}</span>
      <span className="opacity-40">·</span>
      <span>{status}</span>
    </span>
  )
}

// ---------------------------------------------------------------------------
// Per-device chip components
// ---------------------------------------------------------------------------

function MountChip({ device }: { device: ConnectedDevice }) {
  const status = useStore((s) => s.mountStatuses[device.device_id])

  if (!status) {
    return <Chip label={shortName(device)} status="…" variant="slate" />
  }

  if (status.is_slewing) {
    return <Chip label={shortName(device)} status="Slewing" variant="amber" pulse />
  }
  if (status.is_parked) {
    return <Chip label={shortName(device)} status="Parked" variant="slate" />
  }
  if (status.is_tracking) {
    return <Chip label={shortName(device)} status="Tracking" variant="green" />
  }
  return <Chip label={shortName(device)} status="Not tracking" variant="red" />
}

function ImagerChip({ device }: { device: ConnectedDevice }) {
  const busy    = useStore((s) => s.imagerBusy[device.device_id])
  const looping = useStore((s) => s.imagerLooping[device.device_id])
  const exposure = useStore((s) => s.imagerExposures[device.device_id])
  const remaining = useCountdown(exposure)

  if (busy && remaining !== null) {
    const countdown = fmtSeconds(remaining)
    return <Chip label={shortName(device)} status={looping ? `Loop ${countdown}` : countdown} variant="blue" />
  }
  if (looping) {
    // Between subs in a loop — downloading / processing
    return <Chip label={shortName(device)} status="Downloading…" variant="blue" />
  }

  // Show cooler status when active and not yet at target — requires cameraStatus
  // (populated by useStatusPolling)
  return <Chip label={shortName(device)} status="Idle" variant="slate" />
}

function CoolerChip({ device }: { device: ConnectedDevice }) {
  const cam = useStore((s) => s.cameraStatuses[device.device_id])
  if (!cam?.cooler_on || cam.temperature === null) return null
  const temp = cam.temperature.toFixed(0)
  const power = cam.cooler_power !== null ? ` ${cam.cooler_power.toFixed(0)}%` : ''
  return <Chip label={shortName(device)} status={`Cooling ${temp}°C${power}`} variant="blue" />
}

function FocuserChip({ device }: { device: ConnectedDevice }) {
  const status = useStore((s) => s.focuserStatuses[device.device_id])
  if (!status?.is_moving) return null
  const pos = status.position !== null ? ` → ${status.position}` : ''
  return <Chip label={shortName(device)} status={`Moving${pos}`} variant="amber" pulse />
}

function FilterWheelChip({ device }: { device: ConnectedDevice }) {
  const status = useStore((s) => s.filterWheelStatuses[device.device_id])
  if (!status?.is_moving) return null
  return <Chip label={shortName(device)} status="Rotating" variant="amber" pulse />
}

function Phd2Chip() {
  const phd2 = useStore((s) => s.phd2Status)
  if (!phd2?.connected) return null

  const state = phd2.state ?? ''
  const rms = phd2.rms_total

  if (state === 'Guiding') {
    const rmsStr = rms !== null ? ` ${rms.toFixed(2)}"` : ''
    return <Chip label="PHD2" status={`Guiding${rmsStr}`} variant="green" />
  }
  if (state === 'Calibrating') {
    return <Chip label="PHD2" status="Calibrating" variant="amber" pulse />
  }
  if (phd2.is_dithering) {
    return <Chip label="PHD2" status="Dithering" variant="amber" pulse />
  }
  if (state && state !== 'Stopped' && state !== 'Disconnected' && state !== 'Unknown') {
    return <Chip label="PHD2" status={state} variant="slate" />
  }
  return <Chip label="PHD2" status="Connected" variant="slate" />
}

function SolveChip() {
  const jobs = useStore((s) => s.solveJobs)
  const active = Object.values(jobs).find(
    (j) => j.status === 'exposing' || j.status === 'solving',
  )
  if (!active) return null
  const label = active.status === 'exposing' ? 'Exposing…' : 'Solving…'
  return <Chip label="Plate solve" status={label} variant="violet" pulse />
}

// ---------------------------------------------------------------------------
// Status bar
// ---------------------------------------------------------------------------

export function StatusBar() {
  const wsConnected    = useStore((s) => s.wsConnected)
  const devices        = useStore((s) => s.connectedDevices)

  const connected = (kind: ConnectedDevice['kind']) =>
    devices.filter((d) => d.kind === kind && d.state === 'connected')

  const mounts       = connected('mount')
  const cameras      = connected('camera')
  const focusers     = connected('focuser')
  const filterWheels = connected('filter_wheel')

  return (
    <div className="flex items-center gap-2 px-3 h-8 shrink-0 bg-surface-raised border-b border-surface-border overflow-x-auto">
      {/* Device chips */}
      {mounts.map((d)       => <MountChip       key={d.device_id} device={d} />)}
      {cameras.map((d)      => <ImagerChip      key={d.device_id} device={d} />)}
      {cameras.map((d)      => <CoolerChip      key={`cool-${d.device_id}`} device={d} />)}
      {focusers.map((d)     => <FocuserChip     key={d.device_id} device={d} />)}
      {filterWheels.map((d) => <FilterWheelChip key={d.device_id} device={d} />)}
      <Phd2Chip />
      <SolveChip />
      {getAllPluginEntries().map((entry) =>
        entry.StatusChip ? <entry.StatusChip key={entry.to} /> : null,
      )}

      {/* Spacer */}
      <div className="flex-1" />

      {/* WebSocket connection indicator */}
      <span className={`inline-flex items-center gap-1.5 text-xs shrink-0
        ${wsConnected ? 'text-emerald-400' : 'text-rose-400'}`}>
        {wsConnected
          ? <Wifi size={12} />
          : <WifiOff size={12} />}
        <span className="hidden sm:inline">
          {wsConnected ? 'live' : 'reconnecting…'}
        </span>
      </span>
    </div>
  )
}
