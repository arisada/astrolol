import { useEffect, useState } from 'react'
import { Trans, useTranslation } from 'react-i18next'

export function HelloPage() {
  const { t } = useTranslation('hello')
  const [hello, setHello] = useState(false)
  const [status, setStatus] = useState<'idle' | 'saving' | 'error'>('idle')

  useEffect(() => {
    fetch('/plugins/hello/property')
      .then((r) => r.json())
      .then((d) => setHello(d.hello))
      .catch(() => {})
  }, [])

  const toggle = async () => {
    const next = !hello
    setStatus('saving')
    try {
      const r = await fetch('/plugins/hello/property', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ hello: next }),
      })
      const d = await r.json()
      setHello(d.hello)
      setStatus('idle')
    } catch {
      setStatus('error')
    }
  }

  return (
    <div className="p-6 max-w-xl">
      <h1 className="text-lg font-semibold text-slate-100 mb-6">{t('title')}</h1>
      <div className="bg-surface-raised rounded-lg p-4">
        <div className="flex items-center gap-4">
          <input
            id="hello-checkbox"
            type="checkbox"
            checked={hello}
            onChange={toggle}
            disabled={status === 'saving'}
            className="w-4 h-4 accent-accent cursor-pointer disabled:opacity-50"
          />
          <label htmlFor="hello-checkbox" className="text-sm text-slate-200 cursor-pointer select-none">
            {t('property')}
          </label>
          {status === 'saving' && <span className="text-xs text-slate-500">{t('saving')}</span>}
          {status === 'error' && <span className="text-xs text-status-error">{t('failed')}</span>}
        </div>
        <p className="mt-3 text-xs text-slate-500">
          <Trans t={t} i18nKey="about" components={{ code: <code className="text-slate-400" /> }} />
        </p>
      </div>
    </div>
  )
}
