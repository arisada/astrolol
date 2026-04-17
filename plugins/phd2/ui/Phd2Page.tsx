import { useEffect, useState } from 'react'
import { Crosshair, Pause, Play, Square, Target, Wifi, WifiOff } from 'lucide-react'
import { api } from '@/api/client'
import { useStore } from '@/store'
import type { GuidePoint } from '@/store'
import type { Phd2Status } from '@/api/types'
import { Button } from '@/components/ui/button'

// ── Guide graph ───────────────────────────────────────────────────────────────

const GRAPH_W = 340
const GRAPH_H = 100
const GRAPH_RANGE = 2.0  // arcsec full scale (±1")

function GuideGraph({ points }: { points: GuidePoint[] }) {
  if (points.length === 0) {
    return (
      <div className="flex items-center justify-center h-24 text-xs text-slate-600">
        No guide data
      </div>
    )
  }

  const toY = (v: number) => {
    const frac = (v / GRAPH_RANGE) * 0.5 + 0.5
    return Math.round((1 - frac) * GRAPH_H)
  }

  const toX = (i: number) => Math.round((i / Math.max(points.length - 1, 1)) * GRAPH_W)

  const raPath = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${toX(i)},${toY(p.ra)}`).join(' ')
  const decPath = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${toX(i)},${toY(p.dec)}`).join(' ')

  return (
    <svg width={GRAPH_W} height={GRAPH_H} className="w-full" viewBox={`0 0 ${GRAPH_W} ${GRAPH_H}`}>
      <line x1="0" y1={GRAPH_H / 2} x2={GRAPH_W} y2={GRAPH_H / 2}
        stroke="#334155" strokeWidth="1" strokeDasharray="4 4" />
      <path d={raPath} fill="none" stroke="#f97316" strokeWidth="1.5" />
      <path d={decPath} fill="none" stroke="#60a5fa" strokeWidth="1.5" />
      <text x="4" y="10" fontSize="9" fill="#f97316">RA</text>
      <text x="24" y="10" fontSize="9" fill="#60a5fa">Dec</text>
    </svg>
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
        : state === 'LostLock'
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

export function Phd2Page() {
  const guidePoints = useStore((s) => s.phd2GuidePoints)
  const storedStatus = useStore((s) => s.phd2Status)
  const setPhd2Status = useStore((s) => s.setPhd2Status)

  const [status, setStatus] = useState<Phd2Status | null>(storedStatus)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const poll = () => {
      api.phd2.status()
        .then((s) => { setStatus(s); setPhd2Status(s) })
        .catch(() => {})
    }
    poll()
    const id = setInterval(poll, 3_000)
    return () => clearInterval(id)
  }, [setPhd2Status])

  useEffect(() => {
    if (storedStatus) setStatus(storedStatus)
  }, [storedStatus])

  const act = async (fn: () => Promise<void>) => {
    setError(null)
    try { await fn() } catch (e) { setError((e as Error).message) }
  }

  const guiding = status?.state === 'Guiding'
  const paused  = status?.state === 'Paused'
  const connected = status?.connected ?? false

  return (
    <div className="flex flex-col h-full">
    <div className="p-6 max-w-lg mx-auto flex flex-col gap-4 flex-1 overflow-y-auto">

      {/* Header + connect/disconnect */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Crosshair size={20} className="text-accent" />
          <h1 className="text-base font-semibold text-slate-200">PHD2 Guiding</h1>
          {status && <StateBadge state={status.state} connected={status.connected} />}
        </div>
        <Button
          size="sm"
          variant={connected ? 'danger' : 'outline'}
          onClick={() => act(connected ? api.phd2.disconnect : api.phd2.connect)}
        >
          {connected
            ? <><WifiOff size={12} className="mr-1" /> Disconnect</>
            : <><Wifi size={12} className="mr-1" /> Connect</>
          }
        </Button>
      </div>

      {/* Guide graph */}
      <div className="border border-surface-border rounded p-3 bg-surface-raised">
        <p className="text-xs text-slate-500 mb-2">Guide error (arcsec, ±1")</p>
        <GuideGraph points={guidePoints} />
      </div>

      {/* Metrics */}
      <div className="border border-surface-border rounded p-3 bg-surface-raised flex flex-col gap-1.5">
        <Metric label="RMS RA"    value={status?.rms_ra}    unit={'"'} />
        <Metric label="RMS Dec"   value={status?.rms_dec}   unit={'"'} />
        <Metric label="RMS Total" value={status?.rms_total} unit={'"'} />
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
            onClick={() => act(() => api.phd2.guide())}
            disabled={!connected || (guiding && !paused)}
          >
            <Play size={12} className="mr-1" /> Guide
          </Button>

          <Button
            size="sm"
            variant="outline"
            onClick={() => act(paused ? api.phd2.resume : api.phd2.pause)}
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
            onClick={() => act(api.phd2.stop)}
            disabled={!connected || (!guiding && !paused)}
          >
            <Square size={12} className="mr-1" /> Stop
          </Button>

          <Button
            size="sm"
            variant="outline"
            onClick={() => act(() => api.phd2.dither())}
            disabled={!connected || !guiding}
            title="Dither once"
          >
            <Target size={12} className="mr-1" /> Dither
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
