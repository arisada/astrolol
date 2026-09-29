// Global sequencer settings (GET/PUT /plugins/sequencer/settings).
import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
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

const GROUPS: {
  title: string
  bools?: [BoolKey, string][]
  nums?: [NumKey, string, string][]
  texts?: ['journal_dir', string, string][]
}[] = [
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
    title: 'Several cameras',
    nums: [
      ['download_margin_s', 'Allowance after a secondary frame', 's'],
      ['secondary_efficiency_warn', 'Warn when a secondary exposes less than', '(0–1)'],
    ],
  },
  {
    title: 'Guiding loss and stalls',
    nums: [
      ['guide_healthy_after_s', 'Guiding must be steady for', 's before a frame'],
      ['guide_retry_interval_s', 'Retry starting guiding every', 's'],
      ['recenter_after_guide_loss_min', 'Re-centre once after guiding is down for', 'min'],
      ['center_retry_interval_s', 'Retry centering (no stars) every', 's'],
      ['stall_timeout_min', 'Give up on a stall after', 'min (empty = never)'],
      ['uncount_if_unguided_s', 'Retake frames unguided for more than', 's (empty = keep all)'],
    ],
  },
  {
    title: 'Autofocus',
    bools: [['refocus_after_flip', 'Refocus after a meridian flip']],
    nums: [
      ['autofocus_on_temp_delta', 'Refocus when the temperature moved', '°C (empty = off)'],
      ['autofocus_every_min', 'Refocus every', 'min (empty = off)'],
      ['autofocus_retry_interval_s', 'Retry a failed autofocus (no stars) every', 's'],
    ],
  },
  {
    title: 'Session journal',
    texts: [['journal_dir', 'Journal folder', 'empty = "journal" next to the saved images']],
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
      if (v.trim() === '' && NULLABLE.has(k)) {
        ;(next as Record<string, unknown>)[k] = null
        continue
      }
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
          {g.texts?.map(([key, label, hint]) => (
            <label key={key} className="flex items-center gap-3 py-1">
              <span className="text-sm text-slate-300 w-72">{label}</span>
              <div className="w-72">
                <Input inputSize="sm" placeholder={hint} value={settings[key] ?? ''}
                  onChange={(e) => setSettings({ ...settings, [key]: e.target.value.trim() || null })} />
              </div>
            </label>
          ))}
          {g.nums?.map(([key, label, unit]) => (
            <label key={key} className="flex items-center gap-3 py-1">
              <span className="text-sm text-slate-300 w-72">{label}</span>
              <div className="w-24">
                <Input inputSize="sm" value={draft[key] ?? (settings[key] == null ? '' : String(settings[key]))}
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
