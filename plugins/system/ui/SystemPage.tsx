import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Monitor,
  Power,
  RefreshCw,
  RotateCcw,
  Shield,
  Thermometer,
  Wifi,
  WifiOff,
  Radio,
  ChevronDown,
  ChevronUp,
  CheckCircle,
  XCircle,
} from 'lucide-react'
import type { NetworkMode, NetworkStatus, SystemSettings, SystemStatus, SudoSetup, WifiNetwork } from '@/api/types'
import * as api from './api'

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtUptime(seconds: number): string {
  const d = Math.floor(seconds / 86400)
  const h = Math.floor((seconds % 86400) / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (d > 0) return `${d}d ${h}h ${m}m`
  if (h > 0) return `${h}h ${m}m`
  return `${m}m`
}

function fmtBytes(mb: number): string {
  if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`
  return `${mb.toFixed(0)} MB`
}

// ── Gauge bar ─────────────────────────────────────────────────────────────────

function Gauge({ value, label, sublabel, warn = 80, danger = 90 }: {
  value: number
  label: string
  sublabel?: string
  warn?: number
  danger?: number
}) {
  const color =
    value >= danger ? 'bg-rose-500' :
    value >= warn   ? 'bg-amber-500' :
    'bg-emerald-500'

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between text-xs">
        <span className="text-slate-400">{label}</span>
        <span className="text-slate-200 font-mono font-medium">{value.toFixed(0)}%</span>
      </div>
      <div className="h-1.5 bg-surface-overlay rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-700 ${color}`}
          style={{ width: `${Math.min(100, value)}%` }}
        />
      </div>
      {sublabel && <span className="text-xs text-slate-600">{sublabel}</span>}
    </div>
  )
}

// ── Network mode badge ─────────────────────────────────────────────────────────

function NetworkModeBadge({ mode }: { mode: NetworkMode }) {
  const config: Record<NetworkMode, { label: string; cls: string }> = {
    wifi:         { label: 'Wi-Fi',      cls: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30' },
    hotspot:      { label: 'Hotspot',    cls: 'bg-sky-500/20 text-sky-300 border-sky-500/30' },
    disconnected: { label: 'Offline',    cls: 'bg-slate-700/50 text-slate-400 border-slate-600/40' },
    unknown:      { label: 'Unknown',    cls: 'bg-slate-700/50 text-slate-400 border-slate-600/40' },
  }
  const { label, cls } = config[mode]
  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded border text-xs font-medium ${cls}`}>
      {label}
    </span>
  )
}

// ── Signal strength bar ────────────────────────────────────────────────────────

function SignalBars({ signal }: { signal: number }) {
  const bars = Math.round(signal / 25)
  return (
    <div className="flex items-end gap-0.5 h-3">
      {[1, 2, 3, 4].map((b) => (
        <div
          key={b}
          className={`w-1 rounded-sm ${b <= bars ? 'bg-emerald-400' : 'bg-slate-600'}`}
          style={{ height: `${b * 25}%` }}
        />
      ))}
    </div>
  )
}

// ── WiFi network row ──────────────────────────────────────────────────────────

function WifiRow({
  network,
  onConnect,
  connecting,
}: {
  network: WifiNetwork
  onConnect: (ssid: string) => void
  connecting: boolean
}) {
  const [expanded, setExpanded] = useState(false)
  const [password, setPassword] = useState('')

  return (
    <div className={`rounded-lg border transition-colors ${
      network.in_use
        ? 'border-emerald-500/30 bg-emerald-500/5'
        : 'border-surface-border bg-surface-raised'
    }`}>
      <button
        className="w-full flex items-center gap-3 px-3 py-2.5 text-left"
        onClick={() => { if (!network.in_use) setExpanded((v) => !v) }}
      >
        <SignalBars signal={network.signal} />
        <div className="flex-1 min-w-0">
          <p className="text-sm text-slate-200 truncate font-medium">{network.ssid}</p>
          <p className="text-xs text-slate-500">{network.security} · {network.signal}%</p>
        </div>
        {network.in_use && (
          <CheckCircle size={14} className="text-emerald-400 flex-none" />
        )}
        {!network.in_use && (
          expanded
            ? <ChevronUp size={14} className="text-slate-500 flex-none" />
            : <ChevronDown size={14} className="text-slate-500 flex-none" />
        )}
      </button>
      {expanded && !network.in_use && (
        <div className="px-3 pb-3 flex gap-2">
          <input
            type="password"
            placeholder="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && password) onConnect(password) }}
            className="flex-1 rounded bg-surface-overlay border border-surface-border px-2 py-1.5 text-xs text-slate-200 placeholder:text-slate-600 focus:outline-none focus:ring-1 focus:ring-accent"
            autoFocus
          />
          <button
            onClick={() => onConnect(password)}
            disabled={connecting || !password}
            className="px-3 py-1.5 rounded bg-accent hover:bg-accent/80 text-white text-xs font-medium disabled:opacity-50 transition-colors"
          >
            {connecting ? '…' : 'Connect'}
          </button>
        </div>
      )}
    </div>
  )
}

// ── Section card ──────────────────────────────────────────────────────────────

function Section({ title, icon: Icon, children }: {
  title: string
  icon: React.ElementType
  children: React.ReactNode
}) {
  return (
    <div className="rounded-xl border border-surface-border bg-surface-raised overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-3 border-b border-surface-border">
        <Icon size={14} className="text-slate-400" />
        <h2 className="text-xs font-medium text-slate-400 uppercase tracking-wider">{title}</h2>
      </div>
      <div className="p-4">{children}</div>
    </div>
  )
}

// ── Confirm dialog ─────────────────────────────────────────────────────────────

function ConfirmButton({
  label,
  confirmLabel,
  icon: Icon,
  onClick,
  variant = 'danger',
  disabled = false,
}: {
  label: string
  confirmLabel: string
  icon: React.ElementType
  onClick: () => void
  variant?: 'danger' | 'warning'
  disabled?: boolean
}) {
  const [confirming, setConfirming] = useState(false)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const handleClick = () => {
    if (!confirming) {
      setConfirming(true)
      timerRef.current = setTimeout(() => setConfirming(false), 3000)
    } else {
      if (timerRef.current) clearTimeout(timerRef.current)
      setConfirming(false)
      onClick()
    }
  }

  useEffect(() => () => { if (timerRef.current) clearTimeout(timerRef.current) }, [])

  const cls = confirming
    ? variant === 'danger'
      ? 'bg-rose-600 hover:bg-rose-500 text-white border-rose-500'
      : 'bg-amber-600 hover:bg-amber-500 text-white border-amber-500'
    : 'bg-surface-overlay hover:bg-surface-border text-slate-300 border-surface-border'

  return (
    <button
      onClick={handleClick}
      disabled={disabled}
      className={`flex items-center gap-2 px-3 py-2 rounded-lg border text-sm font-medium transition-colors disabled:opacity-50 ${cls}`}
    >
      <Icon size={14} />
      {confirming ? confirmLabel : label}
    </button>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export function SystemPage() {
  const [sysStatus, setSysStatus] = useState<SystemStatus | null>(null)
  const [netStatus, setNetStatus] = useState<NetworkStatus | null>(null)
  const [networks, setNetworks] = useState<WifiNetwork[] | null>(null)
  const [sudoSetup, setSudoSetup] = useState<SudoSetup | null>(null)
  const [settings, setSettings] = useState<SystemSettings | null>(null)

  const [scanning, setScanning] = useState(false)
  const [connecting, setConnecting] = useState<string | null>(null)
  const [hotspotBusy, setHotspotBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [successMsg, setSuccessMsg] = useState<string | null>(null)

  const [showSudoHelp, setShowSudoHelp] = useState(false)
  const [editingSettings, setEditingSettings] = useState(false)
  const [draftSettings, setDraftSettings] = useState<SystemSettings | null>(null)

  const setMsg = (msg: string) => {
    setSuccessMsg(msg)
    setTimeout(() => setSuccessMsg(null), 3000)
  }

  const loadAll = useCallback(async () => {
    try {
      const [sys, net, s] = await Promise.all([
        api.getSystemStatus(),
        api.getNetworkStatus(),
        api.getSettings(),
      ])
      setSysStatus(sys)
      setNetStatus(net)
      setSettings(s)
      setDraftSettings((d) => d ?? s)
      setError(null)
    } catch {
      setError('Cannot reach backend')
    }
  }, [])

  useEffect(() => {
    loadAll()
    const id = setInterval(loadAll, 5000)
    return () => clearInterval(id)
  }, [loadAll])

  useEffect(() => {
    api.getSudoSetup().then(setSudoSetup).catch(() => {})
  }, [])

  const handleScan = async () => {
    setScanning(true)
    setError(null)
    try {
      const nets = await api.scanWifi()
      setNetworks(nets)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Scan failed')
    } finally {
      setScanning(false)
    }
  }

  const handleConnect = async (ssid: string, password: string) => {
    setConnecting(ssid)
    setError(null)
    try {
      await api.connectWifi(ssid, password)
      setMsg(`Connected to ${ssid}`)
      setNetworks(null)
      await loadAll()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Connection failed')
    } finally {
      setConnecting(null)
    }
  }

  const handleDisconnect = async () => {
    setError(null)
    try {
      await api.disconnectWifi()
      setMsg('Disconnected')
      await loadAll()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Disconnect failed')
    }
  }

  const handleStartHotspot = async () => {
    if (!draftSettings) return
    setHotspotBusy(true)
    setError(null)
    try {
      const result = await api.startHotspot(draftSettings.hotspot_ssid, draftSettings.hotspot_password)
      setMsg(`Hotspot "${result.ssid}" started`)
      await loadAll()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to start hotspot')
    } finally {
      setHotspotBusy(false)
    }
  }

  const handleStopHotspot = async () => {
    setHotspotBusy(true)
    setError(null)
    try {
      await api.stopHotspot()
      setMsg('Hotspot stopped')
      await loadAll()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to stop hotspot')
    } finally {
      setHotspotBusy(false)
    }
  }

  const handleSaveSettings = async () => {
    if (!draftSettings) return
    try {
      await api.putSettings(draftSettings)
      setSettings(draftSettings)
      setEditingSettings(false)
      setMsg('Settings saved')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Save failed')
    }
  }

  const isHotspot = netStatus?.mode === 'hotspot'
  const isWifi = netStatus?.mode === 'wifi'
  const nmcliOk = netStatus?.nmcli_available ?? false

  return (
    <div className="p-4 md:p-6 max-w-2xl space-y-4 overflow-y-auto h-full">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-slate-100">System</h1>
        {sysStatus && (
          <span className="text-xs text-slate-500 font-mono">{sysStatus.hostname}</span>
        )}
      </div>

      {/* Global messages */}
      {error && (
        <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-300 flex items-center gap-2">
          <XCircle size={14} className="flex-none" />
          {error}
        </div>
      )}
      {successMsg && (
        <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-300 flex items-center gap-2">
          <CheckCircle size={14} className="flex-none" />
          {successMsg}
        </div>
      )}

      {/* ── System stats ─────────────────────────────────────────────────────── */}
      <Section title="System" icon={Monitor}>
        {sysStatus ? (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-xs mb-3">
              <div className="text-slate-500">Platform <span className="text-slate-300 font-mono">{sysStatus.platform}</span></div>
              <div className="text-slate-500">Uptime <span className="text-slate-300">{fmtUptime(sysStatus.uptime_seconds)}</span></div>
            </div>

            <Gauge
              value={sysStatus.cpu_percent}
              label="CPU"
              sublabel={`${sysStatus.cpu_percent.toFixed(1)}% utilisation`}
            />
            <Gauge
              value={sysStatus.memory_percent}
              label="Memory"
              sublabel={`${fmtBytes(sysStatus.memory_used_mb)} / ${fmtBytes(sysStatus.memory_total_mb)}`}
            />
            <Gauge
              value={sysStatus.disk_percent}
              label="Disk"
              sublabel={`${sysStatus.disk_used_gb.toFixed(1)} GB / ${sysStatus.disk_total_gb.toFixed(1)} GB`}
            />
            {sysStatus.temperature_celsius !== null && (
              <div className="flex items-center gap-3 pt-1">
                <Thermometer size={14} className={
                  sysStatus.temperature_celsius >= 80 ? 'text-rose-400' :
                  sysStatus.temperature_celsius >= 70 ? 'text-amber-400' :
                  'text-slate-400'
                } />
                <span className="text-xs text-slate-400">Temperature</span>
                <span className={`text-sm font-mono font-medium ml-auto ${
                  sysStatus.temperature_celsius >= 80 ? 'text-rose-300' :
                  sysStatus.temperature_celsius >= 70 ? 'text-amber-300' :
                  'text-slate-200'
                }`}>
                  {sysStatus.temperature_celsius.toFixed(1)}°C
                </span>
              </div>
            )}
          </div>
        ) : (
          <p className="text-xs text-slate-600">Loading…</p>
        )}
      </Section>

      {/* ── Network status ────────────────────────────────────────────────────── */}
      <Section title="Network" icon={Wifi}>
        {!nmcliOk && (
          <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs text-amber-300 mb-4">
            NetworkManager (nmcli) not found. WiFi management requires NetworkManager on the host.
          </div>
        )}

        {netStatus && (
          <div className="space-y-3">
            <div className="flex items-center gap-3">
              <NetworkModeBadge mode={netStatus.mode} />
              {netStatus.interface && (
                <span className="text-xs text-slate-500 font-mono">{netStatus.interface}</span>
              )}
            </div>

            {isWifi && netStatus.ssid && (
              <div className="grid grid-cols-2 gap-y-1 text-xs">
                <span className="text-slate-500">SSID</span>
                <span className="text-slate-200 font-mono">{netStatus.ssid}</span>
                {netStatus.ip_address && <>
                  <span className="text-slate-500">IP</span>
                  <span className="text-slate-200 font-mono">{netStatus.ip_address}</span>
                </>}
                {netStatus.gateway && <>
                  <span className="text-slate-500">Gateway</span>
                  <span className="text-slate-200 font-mono">{netStatus.gateway}</span>
                </>}
              </div>
            )}

            {isHotspot && (
              <div className="grid grid-cols-2 gap-y-1 text-xs">
                <span className="text-slate-500">Hotspot SSID</span>
                <span className="text-slate-200 font-mono">{netStatus.hotspot_ssid ?? '—'}</span>
                {netStatus.hotspot_ip && <>
                  <span className="text-slate-500">IP</span>
                  <span className="text-slate-200 font-mono">{netStatus.hotspot_ip}</span>
                </>}
              </div>
            )}

            {netStatus.mode === 'disconnected' && (
              <p className="text-xs text-slate-500">No active wireless connection.</p>
            )}
          </div>
        )}

        {/* Actions */}
        {nmcliOk && (
          <div className="mt-4 flex flex-wrap gap-2">
            {isWifi && (
              <button
                onClick={handleDisconnect}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-surface-border bg-surface-overlay hover:bg-surface-border text-slate-300 text-xs font-medium transition-colors"
              >
                <WifiOff size={12} />
                Disconnect
              </button>
            )}
            {!isHotspot && (
              <button
                onClick={handleStartHotspot}
                disabled={hotspotBusy}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-sky-500/30 bg-sky-500/10 hover:bg-sky-500/20 text-sky-300 text-xs font-medium disabled:opacity-50 transition-colors"
              >
                <Radio size={12} />
                {hotspotBusy ? 'Starting…' : 'Start Hotspot'}
              </button>
            )}
            {isHotspot && (
              <button
                onClick={handleStopHotspot}
                disabled={hotspotBusy}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-500/30 bg-slate-500/10 hover:bg-slate-500/20 text-slate-300 text-xs font-medium disabled:opacity-50 transition-colors"
              >
                <WifiOff size={12} />
                {hotspotBusy ? 'Stopping…' : 'Stop Hotspot'}
              </button>
            )}
            {!isHotspot && (
              <button
                onClick={handleScan}
                disabled={scanning}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-surface-border bg-surface-overlay hover:bg-surface-border text-slate-300 text-xs font-medium disabled:opacity-50 transition-colors"
              >
                <RefreshCw size={12} className={scanning ? 'animate-spin' : ''} />
                {scanning ? 'Scanning…' : 'Scan Networks'}
              </button>
            )}
          </div>
        )}

        {/* WiFi network list */}
        {networks !== null && (
          <div className="mt-4 space-y-2">
            <p className="text-xs text-slate-500 mb-2">{networks.length} network{networks.length !== 1 ? 's' : ''} found</p>
            {networks.length === 0 ? (
              <p className="text-xs text-slate-600">No networks found. Try scanning again.</p>
            ) : (
              networks.map((n) => (
                <WifiRow
                  key={n.bssid}
                  network={n}
                  onConnect={(pw) => handleConnect(n.ssid, pw)}
                  connecting={connecting === n.ssid}
                />
              ))
            )}
          </div>
        )}
      </Section>

      {/* ── Hotspot settings ──────────────────────────────────────────────────── */}
      <Section title="Hotspot Settings" icon={Radio}>
        {draftSettings && (
          <div className="space-y-3">
            <div className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 items-center text-xs">
              <label className="text-slate-400">SSID</label>
              {editingSettings ? (
                <input
                  value={draftSettings.hotspot_ssid}
                  onChange={(e) => setDraftSettings({ ...draftSettings, hotspot_ssid: e.target.value })}
                  className="rounded bg-surface-overlay border border-surface-border px-2 py-1 text-slate-200 focus:outline-none focus:ring-1 focus:ring-accent"
                />
              ) : (
                <span className="text-slate-200 font-mono">{draftSettings.hotspot_ssid}</span>
              )}

              <label className="text-slate-400">Password</label>
              {editingSettings ? (
                <input
                  type="text"
                  value={draftSettings.hotspot_password}
                  onChange={(e) => setDraftSettings({ ...draftSettings, hotspot_password: e.target.value })}
                  className="rounded bg-surface-overlay border border-surface-border px-2 py-1 text-slate-200 focus:outline-none focus:ring-1 focus:ring-accent"
                />
              ) : (
                <span className="text-slate-200 font-mono">{'•'.repeat(Math.min(draftSettings.hotspot_password.length, 12))}</span>
              )}

              <label className="text-slate-400">Interface</label>
              {editingSettings ? (
                <input
                  value={draftSettings.hotspot_interface}
                  onChange={(e) => setDraftSettings({ ...draftSettings, hotspot_interface: e.target.value })}
                  className="rounded bg-surface-overlay border border-surface-border px-2 py-1 text-slate-200 font-mono focus:outline-none focus:ring-1 focus:ring-accent"
                />
              ) : (
                <span className="text-slate-200 font-mono">{draftSettings.hotspot_interface}</span>
              )}
            </div>

            <div className="flex gap-2 pt-1">
              {editingSettings ? (
                <>
                  <button
                    onClick={handleSaveSettings}
                    className="px-3 py-1.5 rounded bg-accent hover:bg-accent/80 text-white text-xs font-medium transition-colors"
                  >
                    Save
                  </button>
                  <button
                    onClick={() => { setDraftSettings(settings); setEditingSettings(false) }}
                    className="px-3 py-1.5 rounded bg-surface-overlay hover:bg-surface-border text-slate-300 text-xs font-medium transition-colors"
                  >
                    Cancel
                  </button>
                </>
              ) : (
                <button
                  onClick={() => setEditingSettings(true)}
                  className="px-3 py-1.5 rounded bg-surface-overlay hover:bg-surface-border text-slate-300 text-xs font-medium transition-colors"
                >
                  Edit
                </button>
              )}
            </div>
          </div>
        )}
      </Section>

      {/* ── Controls ──────────────────────────────────────────────────────────── */}
      <Section title="Controls" icon={Power}>
        <div className="flex flex-wrap gap-2">
          <ConfirmButton
            label="Restart App"
            confirmLabel="Confirm Restart"
            icon={RotateCcw}
            onClick={async () => { try { await api.restartApp() } catch {} }}
            variant="warning"
          />
          <ConfirmButton
            label="Reboot Device"
            confirmLabel="Confirm Reboot"
            icon={RefreshCw}
            onClick={async () => { try { await api.reboot() } catch {} }}
            variant="warning"
          />
          <ConfirmButton
            label="Shutdown Device"
            confirmLabel="Confirm Shutdown"
            icon={Power}
            onClick={async () => { try { await api.shutdown() } catch {} }}
            variant="danger"
          />
        </div>
        <p className="text-xs text-slate-600 mt-3">Click once to arm, click again to confirm. Reboot/Shutdown require passwordless sudo.</p>
      </Section>

      {/* ── Sudo permissions ──────────────────────────────────────────────────── */}
      {sudoSetup && (
        <Section title="Sudo Permissions" icon={Shield}>
          <div className="space-y-2">
            {[
              { label: 'nmcli (network management)', ok: sudoSetup.nmcli_sudo_ok },
              { label: 'reboot', ok: sudoSetup.reboot_sudo_ok },
              { label: 'shutdown', ok: sudoSetup.shutdown_sudo_ok },
            ].map(({ label, ok }) => (
              <div key={label} className="flex items-center gap-2 text-xs">
                {ok
                  ? <CheckCircle size={12} className="text-emerald-400 flex-none" />
                  : <XCircle size={12} className="text-rose-400 flex-none" />
                }
                <span className={ok ? 'text-slate-300' : 'text-slate-500'}>{label}</span>
              </div>
            ))}

            {(!sudoSetup.nmcli_sudo_ok || !sudoSetup.reboot_sudo_ok || !sudoSetup.shutdown_sudo_ok) && (
              <div className="mt-3">
                <button
                  onClick={() => setShowSudoHelp((v) => !v)}
                  className="text-xs text-accent hover:underline flex items-center gap-1"
                >
                  {showSudoHelp ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                  Setup instructions
                </button>
                {showSudoHelp && (
                  <div className="mt-2 rounded bg-surface-overlay border border-surface-border p-3">
                    <p className="text-xs text-slate-400 mb-2">Run these commands on the host as root:</p>
                    {sudoSetup.setup_commands.map((cmd, i) => (
                      <pre key={i} className="text-xs text-slate-300 font-mono break-all whitespace-pre-wrap mb-1">{cmd}</pre>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </Section>
      )}
    </div>
  )
}
