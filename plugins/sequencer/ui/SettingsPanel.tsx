// Global sequencer settings (GET/PUT /plugins/sequencer/settings).
import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ToggleSwitch } from '@/components/ui/toggle-switch'
import type { SequencerSettings } from '@/api/types'
import { getSettings, putSettings } from './api'

type NumKey = { [K in keyof SequencerSettings]: SequencerSettings[K] extends number ? K : never }[keyof SequencerSettings]
type BoolKey = { [K in keyof SequencerSettings]: SequencerSettings[K] extends boolean ? K : never }[keyof SequencerSettings]

const GROUPS: { title: string; bools?: [BoolKey, string][]; nums?: [NumKey, string, string][] }[] = [
  {
    title: 'Mount',
    bools: [['unpark_on_start', 'Unpark when a run starts'], ['park_on_complete', 'Park when the queue is done']],
  },
  {
    title: 'Meridian flip',
    bools: [['meridian_flip_enabled', 'Flip at frame boundaries'], ['center_after_flip', 'Center after the flip']],
    nums: [['meridian_flip_ha_hours', 'Flip at hour angle', 'h past meridian']],
  },
  {
    title: 'Guiding',
    nums: [
      ['guide_settle_pixels', 'Settle threshold', 'px'],
      ['guide_settle_time_s', 'Settle time', 's'],
      ['guide_settle_timeout_s', 'Settle timeout', 's'],
    ],
  },
  {
    title: 'Dither',
    bools: [['dither_ra_only', 'RA only']],
    nums: [['dither_pixels', 'Amount', 'px']],
  },
  {
    title: 'Centering',
    nums: [
      ['center_tolerance_arcsec', 'Tolerance', 'arcsec'],
      ['center_max_attempts', 'Max attempts', ''],
      ['center_exposure_s', 'Exposure', 's'],
      ['center_binning', 'Binning', ''],
    ],
  },
  {
    title: 'Resume and timeouts',
    nums: [
      ['recenter_after_pause_min', 'Re-center after a pause longer than', 'min'],
      ['slew_timeout_s', 'Slew timeout', 's'],
      ['flip_timeout_s', 'Flip timeout', 's'],
      ['park_timeout_s', 'Park timeout', 's'],
      ['exposure_timeout_margin_s', 'Exposure timeout margin', 's'],
    ],
  },
]

export function SettingsPanel() {
  const [settings, setSettings] = useState<SequencerSettings | null>(null)
  const [draft, setDraft] = useState<Record<string, string>>({})
  const [message, setMessage] = useState<string | null>(null)

  useEffect(() => {
    getSettings().then(setSettings).catch((e: Error) => setMessage(e.message))
  }, [])

  if (!settings) return <p className="text-sm text-slate-500">{message ?? 'Loading…'}</p>

  const save = async () => {
    const next = { ...settings }
    for (const [k, v] of Object.entries(draft)) {
      const n = Number(v)
      if (v.trim() === '' || Number.isNaN(n)) { setMessage(`Invalid value for ${k}`); return }
      ;(next as Record<string, unknown>)[k] = n
    }
    try {
      const saved = await putSettings(next)
      setSettings(saved)
      setDraft({})
      setMessage('Saved')
    } catch (e) {
      setMessage((e as Error).message)
    }
  }

  return (
    <div className="flex flex-col gap-5 max-w-xl">
      {GROUPS.map((g) => (
        <section key={g.title}>
          <h3 className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-2">{g.title}</h3>
          {g.bools?.map(([key, label]) => (
            <div key={key} className="flex items-center gap-3 py-1">
              <ToggleSwitch label={label} checked={settings[key]}
                onChange={() => setSettings({ ...settings, [key]: !settings[key] })} />
              <span className="text-sm text-slate-300">{label}</span>
            </div>
          ))}
          {g.nums?.map(([key, label, unit]) => (
            <label key={key} className="flex items-center gap-3 py-1">
              <span className="text-sm text-slate-300 w-64">{label}</span>
              <div className="w-24">
                <Input inputSize="sm" value={draft[key] ?? String(settings[key])}
                  onChange={(e) => setDraft({ ...draft, [key]: e.target.value })} />
              </div>
              <span className="text-xs text-slate-500">{unit}</span>
            </label>
          ))}
        </section>
      ))}
      <div className="flex items-center gap-3">
        <Button size="sm" onClick={save}>Save settings</Button>
        {message && <span className="text-xs text-slate-400">{message}</span>}
      </div>
    </div>
  )
}
