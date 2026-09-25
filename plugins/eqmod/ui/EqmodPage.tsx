import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ToggleSwitch } from '@/components/ui/toggle-switch'
import {
  getDiagnostics, getIndiProxy, getSettings, putSettings,
  type AxisDiagnostics, type EqmodSettings, type IndiProxyStatus, type MountDiagnostics,
} from './api'

const STATUS_FLAGS: { key: string; label: string }[] = [
  { key: 'running', label: 'running' },
  { key: 'tracking_mode', label: 'speed mode' },
  { key: 'fast', label: 'high speed' },
  { key: 'ccw', label: 'CCW' },
  { key: 'blocked', label: 'blocked' },
  { key: 'initialized', label: 'initialized' },
  { key: 'level_switch', label: 'level switch' },
]

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-4 py-0.5">
      <span className="text-slate-500">{label}</span>
      <span className="font-mono text-slate-200 text-right">{value}</span>
    </div>
  )
}

function AxisCard({ name, axis }: { name: string; axis: AxisDiagnostics }) {
  return (
    <div className="bg-surface border border-surface-border rounded p-3 text-xs">
      <p className="text-slate-300 font-medium mb-2">{name} axis{axis.reversed ? ' (reversed)' : ''}</p>
      <Row label="CPR" value={axis.cpr.toLocaleString()} />
      <Row label="High-speed ratio" value={axis.high_speed_ratio} />
      <Row label="Position (counts)" value={axis.position_counts.toLocaleString()} />
      <Row label="Position (deg from home)" value={axis.position_degrees.toFixed(4)} />
      <Row label="Step period (T1)" value={axis.step_period.toLocaleString()} />
      <Row label="Extended status" value={axis.extended_status} />
      <div className="flex flex-wrap gap-1 mt-2">
        {STATUS_FLAGS.map(({ key, label }) => (
          <span
            key={key}
            className={`px-1.5 py-0.5 rounded border ${
              axis.status[key]
                ? 'bg-sky-500/20 text-sky-300 border-sky-500/30'
                : 'bg-slate-700/50 text-slate-500 border-slate-600/40'
            }`}
          >
            {label}
          </span>
        ))}
      </div>
    </div>
  )
}

function MountCard({ d }: { d: MountDiagnostics }) {
  return (
    <div className="bg-surface-raised border border-surface-border rounded p-4 flex flex-col gap-3">
      <div className="flex items-baseline justify-between">
        <p className="text-sm text-slate-200 font-medium">{d.device_id}</p>
        <p className="text-xs text-slate-500 font-mono">{d.port} @ {d.baudrate ?? '?'} baud</p>
      </div>
      {d.error ? (
        <p className="text-xs text-status-error bg-status-error/10 rounded px-3 py-2">{d.error}</p>
      ) : (
        <>
          <div className="text-xs grid grid-cols-2 gap-x-6">
            <Row label="Board version" value={d.board_version ?? '—'} />
            <Row label="Timer frequency" value={d.timer_freq?.toLocaleString() ?? '—'} />
            <Row label="Tracking" value={d.tracking ? d.tracking_mode : 'off'} />
            <Row label="Nudging" value={d.nudging.length ? d.nudging.join(', ') : '—'} />
            <Row label="Guide rate" value={d.guide_rate != null ? `${d.guide_rate}x sidereal` : '—'} />
            <Row label="Guide pulse" value={d.pulsing.length ? d.pulsing.join(', ') : '—'} />
            <Row
              label="Meridian limit"
              value={d.meridian_limit_deg != null ? `${d.meridian_limit_deg}° past the meridian` : '—'}
            />
            <Row
              label="RA margin to limit"
              value={d.ra_axis_margin_deg != null
                ? (d.ra_axis_margin_deg < 0 ? `beyond by ${(-d.ra_axis_margin_deg).toFixed(1)}°` : `${d.ra_axis_margin_deg.toFixed(1)}°`)
                : '—'}
            />
            <Row
              label="Site"
              value={d.location
                ? `${d.location[0].toFixed(4)}°, ${d.location[1].toFixed(4)}°, ${d.location[2].toFixed(0)} m`
                : 'none (no Site in active profile)'}
            />
            <Row label="Parked" value={d.parked ? 'yes' : 'no'} />
            <Row
              label="Park position (counts)"
              value={d.park_counts ? d.park_counts.map((c) => c.toLocaleString()).join(' / ') : '—'}
            />
            <Row
              label="Sync offset"
              value={d.sync_offset
                ? `RA ${(d.sync_offset.ra_axis_h * 60).toFixed(2)} min, Dec ${d.sync_offset.dec_axis_deg.toFixed(3)}°`
                : 'none (not synced)'}
            />
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {Object.entries(d.axes).map(([name, axis]) => (
              <AxisCard key={name} name={name} axis={axis} />
            ))}
          </div>
        </>
      )}
    </div>
  )
}

function SettingsCard() {
  const [settings, setSettings] = useState<EqmodSettings | null>(null)
  const [proxy, setProxy] = useState<IndiProxyStatus | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getSettings().then(setSettings).catch((e: Error) => setError(e.message))
    let cancelled = false
    const loadProxy = () => getIndiProxy().then((p) => { if (!cancelled) setProxy(p) }).catch(() => {})
    loadProxy()
    const id = setInterval(loadProxy, 2000)
    return () => { cancelled = true; clearInterval(id) }
  }, [])

  // Always save the whole object: a partial PUT would reset the other fields to defaults.
  const save = async () => {
    if (settings === null) return
    setSaving(true)
    setError(null)
    try {
      setSettings(await putSettings(settings))
      setProxy(await getIndiProxy())
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const proxyState = !proxy ? '—'
    : !proxy.enabled ? 'disabled'
    : !proxy.indi_available ? 'INDI support unavailable'
    : proxy.loaded ? 'loaded in indiserver'
    : proxy.indiserver_running ? 'registered, not loaded yet'
    : 'registered: loads when indiserver starts (first INDI device)'

  return (
    <div className="bg-surface-raised border border-surface-border rounded p-4 flex flex-col gap-4 text-sm">
      <p className="text-slate-300 font-medium">Settings</p>
      <div className="flex items-center gap-3">
        <span className="text-slate-400 w-40">Polar scope LED</span>
        <input
          type="range" min={0} max={100}
          value={settings?.led_brightness ?? 0}
          disabled={settings === null}
          onChange={(e) => settings && setSettings({ ...settings, led_brightness: Number(e.target.value) })}
          className="flex-1"
        />
        <span className="font-mono text-slate-200 w-10 text-right">{settings?.led_brightness ?? '—'}%</span>
      </div>

      <div className="flex flex-col gap-2 border-t border-surface-border pt-4">
        <div className="flex items-center gap-3">
          <ToggleSwitch
            checked={settings?.indi_proxy_enabled ?? false}
            disabled={settings === null}
            onChange={() => settings && setSettings({ ...settings, indi_proxy_enabled: !settings.indi_proxy_enabled })}
            label="INDI mount proxy"
          />
          <span className="text-slate-300">INDI mount proxy</span>
          <span className="text-xs text-slate-500 ml-auto">{proxyState}</span>
        </div>
        <label className="flex items-center gap-3 text-xs">
          <span className="text-slate-500 w-40">astrolol API URL (from the proxy)</span>
          <Input
            value={settings?.indi_proxy_api_url ?? ''}
            disabled={settings === null}
            onChange={(e) => settings && setSettings({ ...settings, indi_proxy_api_url: e.target.value })}
            className="font-mono"
          />
        </label>
        <div className="text-xs text-slate-500 space-y-1">
          <p>
            Publishes the connected mount on astrolol&apos;s indiserver as{' '}
            <span className="font-mono text-slate-300">{proxy?.device_name ?? 'astrolol Mount Proxy'}</span>
            {' '}(a relay to astrolol&apos;s REST API, not a real mount driver).
          </p>
          <p>
            PHD2: connect to this machine&apos;s indiserver (port 7624), pick your INDI guide camera, and
            pick <span className="font-mono">astrolol Mount Proxy</span> as the mount. Guide pulses run at
            the mount&apos;s guide rate (connect param <span className="font-mono">guide_rate</span>, 0.5x sidereal by default).
          </p>
          <p>
            INDI drivers that snoop a telescope (e.g. the CCD simulator&apos;s star field, or FITS headers):
            set their active telescope to <span className="font-mono">astrolol Mount Proxy</span>.
          </p>
        </div>
      </div>

      <div className="flex items-center gap-3">
        <Button type="button" size="sm" disabled={settings === null || saving} onClick={save}>
          {saving ? 'Saving…' : 'Save'}
        </Button>
        {error && <span className="text-xs text-status-error">{error}</span>}
      </div>
    </div>
  )
}

export function EqmodPage() {
  const [mounts, setMounts] = useState<MountDiagnostics[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const load = () =>
      getDiagnostics()
        .then((d) => { if (!cancelled) { setMounts(d); setError(null) } })
        .catch((e: Error) => { if (!cancelled) setError(e.message) })
    load()
    const id = setInterval(load, 2000)
    return () => { cancelled = true; clearInterval(id) }
  }, [])

  return (
    <div className="p-6 max-w-4xl flex flex-col gap-4">
      <h1 className="text-lg font-semibold text-slate-100">EQMOD</h1>
      {error && <p className="text-xs text-status-error">{error}</p>}
      {mounts !== null && mounts.length === 0 && (
        <div className="text-sm text-slate-500 space-y-1">
          <p>No real eqmod mount connected.</p>
          <p className="text-xs">
            Equipment → Load driver → Mount → Other adapter → <span className="font-mono">eqmod</span>, with
            params <span className="font-mono">{'{"port": "/dev/ttyUSB0"}'}</span>. Add{' '}
            <span className="font-mono">"baudrate"</span> to skip auto-detection (9600 for an EQMOD cable,
            115200 for the AZ-EQ6 built-in USB), and <span className="font-mono">"ra_reverse"</span> /{' '}
            <span className="font-mono">"dec_reverse"</span> if a nudge moves the wrong way.
          </p>
        </div>
      )}
      {mounts?.map((d) => <MountCard key={d.device_id} d={d} />)}
      <SettingsCard />
    </div>
  )
}
