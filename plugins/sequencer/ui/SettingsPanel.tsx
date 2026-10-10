// Global sequencer settings (GET/PUT /plugins/sequencer/settings).
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { NumberStepper } from '@/components/ui/number-stepper'
import { ToggleSwitch } from '@/components/ui/toggle-switch'
import type { SequencerSettings } from '@/api/types'
import { getSettings, putSettings } from './api'

type NumKey = {
  [K in keyof SequencerSettings]: SequencerSettings[K] extends number | null ? (SequencerSettings[K] extends boolean ? never : K) : never
}[keyof SequencerSettings]
const NULLABLE = new Set<string>([
  'stall_timeout_min', 'uncount_if_unguided_s', 'autofocus_on_temp_delta', 'autofocus_every_min',
])
type BoolKey = { [K in keyof SequencerSettings]: SequencerSettings[K] extends boolean ? K : never }[keyof SequencerSettings]

// Labels, units and hints live in the catalogue under settings.fields.<key>.
const GROUPS: {
  id: string
  bools?: BoolKey[]
  nums?: NumKey[]
  temps?: 'warm_temperature_c'[]
  texts?: 'journal_dir'[]
}[] = [
  { id: 'mount', bools: ['unpark_on_start', 'park_on_complete'] },
  { id: 'meridian', bools: ['meridian_flip_enabled', 'center_after_flip'], nums: ['meridian_flip_ha_hours'] },
  { id: 'guiding', nums: ['guide_settle_pixels', 'guide_settle_time_s', 'guide_settle_timeout_s'] },
  { id: 'dither', bools: ['dither_ra_only'], nums: ['dither_pixels'] },
  { id: 'centering', nums: ['center_tolerance_arcsec', 'center_max_attempts', 'center_exposure_s', 'center_binning'] },
  { id: 'cooling', bools: ['warm_on_complete'], temps: ['warm_temperature_c'], nums: ['cooling_tolerance_c', 'cooling_timeout_min'] },
  { id: 'cameras', nums: ['download_margin_s', 'secondary_efficiency_warn'] },
  {
    id: 'stalls',
    nums: [
      'guide_healthy_after_s', 'guide_retry_interval_s', 'recenter_after_guide_loss_min',
      'center_retry_interval_s', 'stall_timeout_min', 'uncount_if_unguided_s',
    ],
  },
  {
    id: 'autofocus',
    bools: ['refocus_after_flip'],
    nums: ['autofocus_on_temp_delta', 'autofocus_every_min', 'autofocus_retry_interval_s'],
  },
  { id: 'journal', texts: ['journal_dir'] },
  {
    id: 'resume',
    nums: ['recenter_after_pause_min', 'slew_timeout_s', 'flip_timeout_s', 'park_timeout_s', 'exposure_timeout_margin_s'],
  },
]

export function SettingsPanel() {
  const { t } = useTranslation('sequencer')
  const [settings, setSettings] = useState<SequencerSettings | null>(null)
  const [draft, setDraft] = useState<Record<string, string>>({})
  const [message, setMessage] = useState<string | null>(null)

  useEffect(() => {
    getSettings().then(setSettings).catch((e: Error) => setMessage(e.message))
  }, [])

  if (!settings) return <p className="text-sm text-slate-500">{message ?? t('loading')}</p>

  const save = async () => {
    const next = { ...settings }
    for (const [k, v] of Object.entries(draft)) {
      if (v.trim() === '' && NULLABLE.has(k)) {
        ;(next as Record<string, unknown>)[k] = null
        continue
      }
      const n = Number(v)
      if (v.trim() === '' || Number.isNaN(n)) { setMessage(t('settings.invalid', { field: t(`settings.fields.${k}.label`, { defaultValue: k }) })); return }
      ;(next as Record<string, unknown>)[k] = n
    }
    try {
      const saved = await putSettings(next)
      setSettings(saved)
      setDraft({})
      setMessage(t('settings.saved'))
    } catch (e) {
      setMessage((e as Error).message)
    }
  }

  return (
    <div className="flex flex-col gap-5 max-w-xl">
      {GROUPS.map((g) => (
        <section key={g.id}>
          <h3 className="font-medium text-slate-500 label-caps mb-2">{t(`settings.groups.${g.id}`)}</h3>
          {g.bools?.map((key) => (
            <div key={key} className="flex items-center gap-3 py-1">
              <ToggleSwitch label={t(`settings.fields.${key}.label`)} checked={settings[key]}
                onChange={() => setSettings({ ...settings, [key]: !settings[key] })} />
              <span className="text-sm text-slate-300">{t(`settings.fields.${key}.label`)}</span>
            </div>
          ))}
          {g.temps?.map((key) => (
            <div key={key} className="flex items-center gap-3 py-1">
              <span className="text-sm text-slate-300 w-72">{t(`settings.fields.${key}.label`)}</span>
              <NumberStepper value={settings[key]} unit="°C" step={1} min={-60} max={40}
                disabled={!settings.warm_on_complete}
                onChange={(v) => setSettings({ ...settings, [key]: v })} />
            </div>
          ))}
          {g.texts?.map((key) => (
            <label key={key} className="flex items-center gap-3 py-1">
              <span className="text-sm text-slate-300 w-72">{t(`settings.fields.${key}.label`)}</span>
              <div className="w-72">
                <Input inputSize="sm" placeholder={t(`settings.fields.${key}.hint`)} value={settings[key] ?? ''}
                  onChange={(e) => setSettings({ ...settings, [key]: e.target.value.trim() || null })} />
              </div>
            </label>
          ))}
          {g.nums?.map((key) => (
            <label key={key} className="flex items-center gap-3 py-1">
              <span className="text-sm text-slate-300 w-72">{t(`settings.fields.${key}.label`)}</span>
              <div className="w-24">
                <Input inputSize="sm" value={draft[key] ?? (settings[key] == null ? '' : String(settings[key]))}
                  onChange={(e) => setDraft({ ...draft, [key]: e.target.value })} />
              </div>
              <span className="text-xs text-slate-500">{t(`settings.fields.${key}.unit`, { defaultValue: '' })}</span>
            </label>
          ))}
        </section>
      ))}
      <div className="flex items-center gap-3">
        <Button size="sm" onClick={save}>{t('settings.save')}</Button>
        {message && <span className="text-xs text-slate-400">{message}</span>}
      </div>
    </div>
  )
}
