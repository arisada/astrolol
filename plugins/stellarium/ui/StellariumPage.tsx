import { useEffect, useState } from 'react'
import { Trans, useTranslation } from 'react-i18next'

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

const RICH = {
  hl: <span className="text-slate-300" />,
  mono: <span className="text-slate-300 font-mono" />,
}

export function StellariumPage() {
  const { t } = useTranslation('stellarium')
  const [status, setStatus] = useState<StellariumStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const load = async () => {
    try {
      const s = await fetch('/plugins/stellarium/status').then((r) => r.json())
      setStatus(s)
      setError(null)
    } catch {
      setError(t('unreachable'))
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
      await fetch(status.running ? '/plugins/stellarium/stop' : '/plugins/stellarium/start', { method: 'POST' })
      await load()
    } finally {
      setBusy(false)
    }
  }

  if (error) return <div className="p-6 text-status-error text-sm">{error}</div>
  if (!status) return <div className="p-6 text-slate-500 text-sm">{t('loading')}</div>

  return (
    <div className="p-6 max-w-xl">
      <h1 className="text-lg font-semibold text-slate-100 mb-6">{t('title')}</h1>

      <div className="bg-surface-raised rounded-lg p-4 space-y-3 mb-6">
        <div className="flex items-center justify-between">
          <span className="text-sm text-slate-300 flex items-center">
            <StatusDot ok={status.running} />
            {status.running ? t('running') : t('stopped')}
          </span>
          <button
            onClick={toggle}
            disabled={busy}
            className={`px-3 py-1.5 rounded text-sm font-medium transition-colors disabled:opacity-50
              ${status.running
                ? 'bg-slate-600 hover:bg-slate-500 text-slate-100'
                : 'bg-accent hover:bg-accent/80 text-accent-fg'}`}
          >
            {busy ? '…' : status.running ? t('stop') : t('start')}
          </button>
        </div>
        <div className="flex gap-6 text-xs text-slate-500 pt-1 border-t border-slate-700">
          <span>{t('port')} <span className="text-slate-300 font-mono">{status.port}</span></span>
          <span>{t('clients')} <span className="text-slate-300">{status.clients_connected}</span></span>
        </div>
      </div>

      <div className="text-sm text-slate-400 space-y-3">
        <p className="font-semibold text-slate-300">{t('howto.title')}</p>
        <ol className="list-decimal list-inside space-y-1.5 text-xs text-slate-500">
          {[1, 2, 3, 4, 5, 6, 7].map((n) => (
            <li key={n}>
              <Trans t={t} i18nKey={`howto.step${n}`} values={{ port: status.port }} components={RICH} />
            </li>
          ))}
        </ol>
        <p className="text-xs text-slate-600 pt-2">{t('howto.footer')}</p>
      </div>
    </div>
  )
}
