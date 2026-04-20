import { useEffect, useState } from 'react'
import { api } from '@/api/client'

interface Lx200Status {
  running: boolean
  port: number
  clients_connected: number
}

function StatusDot({ ok }: { ok: boolean }) {
  return (
    <span
      className={`inline-block w-2 h-2 rounded-full mr-2 ${ok ? 'bg-status-connected' : 'bg-slate-500'}`}
    />
  )
}

function SetupInstructions({ port }: { port: number }) {
  return (
    <div className="mt-6 text-sm text-slate-400 space-y-4">
      <p className="font-semibold text-slate-300">How to connect a planetarium app</p>

      <div>
        <p className="text-slate-300 mb-1">Stellarium</p>
        <ol className="list-decimal list-inside space-y-1 text-xs text-slate-500">
          <li>Plugins → Telescope Control → enable → configure</li>
          <li>Add telescope → type: <span className="text-slate-300 font-mono">TCP</span></li>
          <li>Host: <span className="text-slate-300 font-mono">astrolol-host</span>, Port: <span className="text-slate-300 font-mono">{port}</span></li>
        </ol>
      </div>

      <div>
        <p className="text-slate-300 mb-1">SkySafari</p>
        <ol className="list-decimal list-inside space-y-1 text-xs text-slate-500">
          <li>Settings → Telescope → Setup</li>
          <li>Telescope type: <span className="text-slate-300 font-mono">Meade LX200 Classic</span></li>
          <li>Mount type: <span className="text-slate-300 font-mono">Alt-Az</span> or <span className="text-slate-300 font-mono">Equatorial</span></li>
          <li>Connect via: <span className="text-slate-300 font-mono">WiFi</span>, IP: astrolol-host, Port: <span className="text-slate-300 font-mono">{port}</span></li>
        </ol>
      </div>

      <div>
        <p className="text-slate-300 mb-1">Cartes du Ciel</p>
        <ol className="list-decimal list-inside space-y-1 text-xs text-slate-500">
          <li>Telescope → Setup → driver: <span className="text-slate-300 font-mono">Meade LX200</span></li>
          <li>Connection: <span className="text-slate-300 font-mono">TCP</span>, host: astrolol-host, port: <span className="text-slate-300 font-mono">{port}</span></li>
        </ol>
      </div>

      <p className="text-xs text-slate-600 pt-2">
        Coordinates exchanged in J2000 (ICRS). GoTo slews the mount; Sync updates the mount's
        pointing model. Stop/Abort halts any ongoing slew.
      </p>
    </div>
  )
}

export function Lx200Page() {
  const [status, setStatus] = useState<Lx200Status | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const load = async () => {
    try {
      const s = await fetch('/lx200/status').then((r) => r.json())
      setStatus(s)
      setError(null)
    } catch {
      setError('Cannot reach backend')
    }
  }

  useEffect(() => {
    load()
    const id = setInterval(load, 2000)
    return () => clearInterval(id)
  }, [])

  const toggle = async () => {
    if (!status) return
    setBusy(true)
    try {
      await fetch(status.running ? '/lx200/stop' : '/lx200/start', { method: 'POST' })
      await load()
    } finally {
      setBusy(false)
    }
  }

  if (error) {
    return (
      <div className="p-6 text-status-error text-sm">{error}</div>
    )
  }

  if (!status) {
    return <div className="p-6 text-slate-500 text-sm">Loading…</div>
  }

  return (
    <div className="p-6 max-w-xl">
      <h1 className="text-lg font-semibold text-slate-100 mb-6">LX200 Server</h1>

      <div className="bg-surface-raised rounded-lg p-4 space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-sm text-slate-300 flex items-center">
            <StatusDot ok={status.running} />
            {status.running ? 'Running' : 'Stopped'}
          </span>
          <button
            onClick={toggle}
            disabled={busy}
            className={`px-3 py-1.5 rounded text-sm font-medium transition-colors disabled:opacity-50
              ${status.running
                ? 'bg-slate-600 hover:bg-slate-500 text-white'
                : 'bg-accent hover:bg-accent/80 text-white'}`}
          >
            {busy ? '…' : status.running ? 'Stop' : 'Start'}
          </button>
        </div>

        <div className="flex gap-6 text-xs text-slate-500 pt-1 border-t border-slate-700">
          <span>
            Port: <span className="text-slate-300 font-mono">{status.port}</span>
          </span>
          <span>
            Clients connected: <span className="text-slate-300">{status.clients_connected}</span>
          </span>
        </div>
      </div>

      <SetupInstructions port={status.port} />
    </div>
  )
}
