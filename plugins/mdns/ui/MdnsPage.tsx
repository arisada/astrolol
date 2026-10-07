import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { PillGroup } from '@/components/ui/pill-group'
import * as api from './api'
import type { MdnsSettings } from './api'

const EMPTY: MdnsSettings = {
  advertised_host: null,
  advertised_port: null,
  scheme: 'http',
  instance_name: null,
}

function currentPageAddress(): { host: string; port: number; scheme: 'http' | 'https' } {
  const scheme = window.location.protocol === 'https:' ? 'https' : 'http'
  const port = window.location.port
    ? Number(window.location.port)
    : scheme === 'https' ? 443 : 80
  return { host: window.location.hostname, port, scheme }
}

export function MdnsPage() {
  const { t } = useTranslation('mdns')
  const [settings, setSettings] = useState<MdnsSettings | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const [restarting, setRestarting] = useState(false)

  useEffect(() => {
    api.getSettings().then(setSettings).catch(() => setError(t('unreachable')))
  }, [])

  const update = (patch: Partial<MdnsSettings>) => {
    setSettings((s) => (s ? { ...s, ...patch } : s))
    setSaved(false)
  }

  const handleAutofill = () => {
    const { host, port, scheme } = currentPageAddress()
    update({ advertised_host: host, advertised_port: port, scheme })
  }

  const handleSave = async () => {
    if (!settings) return
    setSaving(true)
    setError(null)
    try {
      const result = await api.putSettings(settings)
      setSettings(result)
      setSaved(true)
    } catch (e) {
      setError(e instanceof Error ? e.message : t('saveFailed'))
    } finally {
      setSaving(false)
    }
  }

  const handleRestart = async () => {
    setRestarting(true)
    try {
      await fetch('/admin/restart', { method: 'POST' })
    } catch {
      // expected — process may die before responding
    }
    const poll = async () => {
      try {
        const r = await fetch('/health')
        if (r.ok) { window.location.reload(); return }
      } catch { /* still down */ }
      setTimeout(poll, 800)
    }
    setTimeout(poll, 1200)
  }

  const s = settings ?? EMPTY

  return (
    <div className="p-4 md:p-6 max-w-lg space-y-4 overflow-y-auto h-full">
      <h1 className="text-lg font-semibold text-slate-100">{t('title')}</h1>
      <p className="text-xs text-slate-500">{t('intro')}</p>

      {error && (
        <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
          {error}
        </div>
      )}
      {saved && !error && (
        <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-300 flex items-center justify-between gap-3">
          <span>{restarting ? t('restarting') : t('savedRestart')}</span>
          {!restarting && (
            <button
              onClick={handleRestart}
              className="px-2.5 py-1 rounded bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-medium transition-colors flex-none"
            >
              {t('restart')}
            </button>
          )}
        </div>
      )}

      <Card title={t('card')} className="p-4 space-y-4">
        <div className="flex items-center justify-between gap-2">
          <p className="text-xs text-slate-500">{t('autofillHint')}</p>
          <button
            onClick={handleAutofill}
            className="px-2.5 py-1 rounded bg-surface-overlay hover:bg-surface-border text-slate-300 text-xs font-medium transition-colors flex-none"
          >
            {t('autofill')}
          </button>
        </div>

        <div>
          <label className="text-xs text-slate-400 block mb-1">{t('instanceName')}</label>
          <Input
            value={s.instance_name ?? ''}
            placeholder={t('instanceNamePlaceholder')}
            onChange={(e) => update({ instance_name: e.target.value || null })}
          />
        </div>

        <div>
          <label className="text-xs text-slate-400 block mb-1">{t('host')}</label>
          <Input
            value={s.advertised_host ?? ''}
            placeholder={t('hostPlaceholder')}
            onChange={(e) => update({ advertised_host: e.target.value || null })}
          />
          <p className="text-xs text-slate-600 mt-1">{t('hostHint')}</p>
        </div>

        <div>
          <label className="text-xs text-slate-400 block mb-1">{t('port')}</label>
          <Input
            type="number"
            value={s.advertised_port ?? ''}
            placeholder={t('portPlaceholder')}
            onChange={(e) => update({ advertised_port: e.target.value ? Number(e.target.value) : null })}
          />
          <p className="text-xs text-slate-600 mt-1">{t('portHint')}</p>
        </div>

        <PillGroup
          label={t('scheme')}
          options={['http', 'https'] as const}
          value={s.scheme}
          onChange={(scheme) => update({ scheme })}
        />

        <button
          onClick={handleSave}
          disabled={saving || !settings}
          className="px-3 py-1.5 rounded bg-accent hover:bg-accent/80 text-accent-fg text-xs font-medium disabled:opacity-50 transition-colors"
        >
          {saving ? t('saving') : t('save')}
        </button>
      </Card>
    </div>
  )
}
