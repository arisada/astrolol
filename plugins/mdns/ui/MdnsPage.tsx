import { useEffect, useState } from 'react'
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

export function MdnsPage() {
  const [settings, setSettings] = useState<MdnsSettings | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    api.getSettings().then(setSettings).catch(() => setError('Cannot reach backend'))
  }, [])

  const update = (patch: Partial<MdnsSettings>) => {
    setSettings((s) => (s ? { ...s, ...patch } : s))
    setSaved(false)
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
      setError(e instanceof Error ? e.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  const s = settings ?? EMPTY

  return (
    <div className="p-4 md:p-6 max-w-lg space-y-4 overflow-y-auto h-full">
      <h1 className="text-lg font-semibold text-slate-100">mDNS Discovery</h1>
      <p className="text-xs text-slate-500">
        Advertises this server on the local network so clients (e.g. the Android app) can
        find it without typing an IP. astrolol cannot detect the address/port a client
        should use on its own — especially behind a reverse proxy doing TLS — so it needs
        to be set here explicitly. Changes take effect on next restart.
      </p>

      {error && (
        <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
          {error}
        </div>
      )}
      {saved && !error && (
        <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-300">
          Saved — restart astrolol for this to take effect.
        </div>
      )}

      <Card title="Advertisement" className="p-4 space-y-4">
        <div>
          <label className="text-xs text-slate-400 block mb-1">Instance name</label>
          <Input
            value={s.instance_name ?? ''}
            placeholder="Defaults to this machine's hostname"
            onChange={(e) => update({ instance_name: e.target.value || null })}
          />
        </div>

        <div>
          <label className="text-xs text-slate-400 block mb-1">Advertised host</label>
          <Input
            value={s.advertised_host ?? ''}
            placeholder="Auto-detect local IP (leave blank)"
            onChange={(e) => update({ advertised_host: e.target.value || null })}
          />
          <p className="text-xs text-slate-600 mt-1">
            An IP or hostname. Set this when the deployment fronts astrolol with a reverse
            proxy on a different host, or when auto-detection picks the wrong interface.
          </p>
        </div>

        <div>
          <label className="text-xs text-slate-400 block mb-1">Advertised port</label>
          <Input
            type="number"
            value={s.advertised_port ?? ''}
            placeholder="e.g. 443 behind nginx, 8000 with no proxy"
            onChange={(e) => update({ advertised_port: e.target.value ? Number(e.target.value) : null })}
          />
          <p className="text-xs text-slate-600 mt-1">
            Required — nothing is advertised until this is set.
          </p>
        </div>

        <PillGroup
          label="Scheme"
          options={['http', 'https'] as const}
          value={s.scheme}
          onChange={(scheme) => update({ scheme })}
        />

        <button
          onClick={handleSave}
          disabled={saving || !settings}
          className="px-3 py-1.5 rounded bg-accent hover:bg-accent/80 text-white text-xs font-medium disabled:opacity-50 transition-colors"
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
      </Card>
    </div>
  )
}
