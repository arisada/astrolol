import { useEffect, useState } from 'react'
import { Trans, useTranslation } from 'react-i18next'

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

const RICH = { mono: <span className="text-slate-300 font-mono" /> }

const SETUP_APPS = [
  { name: 'Stellarium', key: 'stellarium', steps: 3 },
  { name: 'SkySafari', key: 'skysafari', steps: 4 },
  { name: 'Cartes du Ciel', key: 'cartes', steps: 2 },
] as const

function SetupInstructions({ port }: { port: number }) {
  const { t } = useTranslation('lx200')
  return (
    <div className="mt-6 text-sm text-slate-400 space-y-4">
      <p className="font-semibold text-slate-300">{t('setup.title')}</p>

      {SETUP_APPS.map(({ name, key, steps }) => (
        <div key={key}>
          <p className="text-slate-300 mb-1">{name}</p>
          <ol className="list-decimal list-inside space-y-1 text-xs text-slate-500">
            {Array.from({ length: steps }, (_, n) => (
              <li key={n}>
                <Trans t={t} i18nKey={`setup.${key}.step${n + 1}`} values={{ port }} components={RICH} />
              </li>
            ))}
          </ol>
        </div>
      ))}

      <p className="text-xs text-slate-600 pt-2">{t('setup.footer')}</p>
    </div>
  )
}

export function Lx200Page() {
  const { t } = useTranslation('lx200')
  const [status, setStatus] = useState<Lx200Status | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const load = async () => {
    try {
      const s = await fetch('/plugins/lx200/status').then((r) => r.json())
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
      await fetch(status.running ? '/plugins/lx200/stop' : '/plugins/lx200/start', { method: 'POST' })
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
    return <div className="p-6 text-slate-500 text-sm">{t('loading')}</div>
  }

  return (
    <div className="p-6 max-w-xl">
      <h1 className="text-lg font-semibold text-slate-100 mb-6">{t('title')}</h1>

      <div className="bg-surface-raised rounded-lg p-4 space-y-3">
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
                ? 'bg-slate-600 hover:bg-slate-500 text-white'
                : 'bg-accent hover:bg-accent/80 text-white'}`}
          >
            {busy ? '…' : status.running ? t('stop') : t('start')}
          </button>
        </div>

        <div className="flex gap-6 text-xs text-slate-500 pt-1 border-t border-slate-700">
          <span>
            {t('port')} <span className="text-slate-300 font-mono">{status.port}</span>
          </span>
          <span>
            {t('clients')} <span className="text-slate-300">{status.clients_connected}</span>
          </span>
        </div>
      </div>

      <SetupInstructions port={status.port} />
    </div>
  )
}
