import { useEffect, useState } from 'react'

interface StellariumStatus {
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

export function StellariumPage() {
  const [status, setStatus] = useState<StellariumStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const load = async () => {
    try {
      const s = await fetch('/stellarium/status').then((r) => r.json())
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
      await fetch(status.running ? '/stellarium/stop' : '/stellarium/start', { method: 'POST' })
      await load()
    } finally {
      setBusy(false)
    }
  }

  if (error) return <div className="p-6 text-status-error text-sm">{error}</div>
  if (!status) return <div className="p-6 text-slate-500 text-sm">Loading…</div>

  return (
    <div className="p-6 max-w-xl">
      <h1 className="text-lg font-semibold text-slate-100 mb-6">Stellarium Server</h1>

      <div className="bg-surface-raised rounded-lg p-4 space-y-3 mb-6">
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
          <span>Port: <span className="text-slate-300 font-mono">{status.port}</span></span>
          <span>Clients: <span className="text-slate-300">{status.clients_connected}</span></span>
        </div>
      </div>

      <div className="text-sm text-slate-400 space-y-3">
        <p className="font-semibold text-slate-300">How to connect Stellarium</p>
        <ol className="list-decimal list-inside space-y-1.5 text-xs text-slate-500">
          <li>Plugins → Telescope Control → enable the plugin → configure</li>
          <li>Click <span className="text-slate-300">Add a new telescope</span></li>
          <li>
            Telescope controlled by:{' '}
            <span className="text-slate-300 font-mono">3rd party software or remote computer</span>
          </li>
          <li>
            Connection type: <span className="text-slate-300 font-mono">TCP</span>
          </li>
          <li>
            Host: <span className="text-slate-300 font-mono">astrolol-host</span>, Port:{' '}
            <span className="text-slate-300 font-mono">{status.port}</span>
          </li>
          <li>Save and connect. The telescope reticle should appear on the sky.</li>
        </ol>
        <p className="text-xs text-slate-600 pt-2">
          Right-click any object → Current object → Slew telescope to issue a GoTo.
          Coordinates are J2000 (ICRS). Position is pushed to Stellarium every 500 ms.
        </p>
      </div>
    </div>
  )
}
