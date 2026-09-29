// Guide simulator: status, manual guiding controls, fault injection and settings.
import { useCallback, useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { EventLog } from '@/components/ui/event-log'
import { Input } from '@/components/ui/input'
import { ToggleSwitch } from '@/components/ui/toggle-switch'
import * as sim from './api'

const fmt = (v: number | null | undefined, digits = 2) => (v == null ? '—' : v.toFixed(digits))

export function GuideSimPage() {
  const [report, setReport] = useState<sim.SimReport | null>(null)
  const [settings, setSettings] = useState<sim.GuideSimSettings | null>(null)
  const [draft, setDraft] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  const refresh = useCallback(() => {
    sim.getStatus().then((r) => { setReport(r); setError(null) }).catch((e: Error) => setError(e.message))
  }, [])
  useEffect(() => {
    refresh()
    sim.getSettings().then(setSettings).catch(() => {})
    const t = setInterval(refresh, 1000)   // a debugging tool: polling its own status is fine
    return () => clearInterval(t)
  }, [refresh])

  const act = (fn: () => Promise<unknown>) => () => {
    fn().then(refresh).catch((e: Error) => setError(e.message))
  }

  const saveSettings = async () => {
    if (!settings) return
    const next = { ...settings } as Record<string, unknown>
    for (const [k, v] of Object.entries(draft)) {
      const n = Number(v)
      if (v.trim() === '' || !(n > 0)) { setMessage(`Invalid ${k}`); return }
      next[k] = n
    }
    try {
      setSettings(await sim.putSettings(next as unknown as sim.GuideSimSettings))
      setDraft({})
      setMessage('Saved')
    } catch (e) {
      setMessage((e as Error).message)
    }
  }

  const st = report?.status
  const h = report?.health
  const w = report?.last_minute
  const f = report?.faults

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-3xl flex flex-col gap-6">
          <div>
            <h1 className="text-lg font-semibold text-slate-100">Guide Simulator</h1>
            <p className="text-xs text-slate-500 mt-1">
              A guider without hardware. It stands in for PHD2 as the application's guider
              (sequencer, loop dithering); use the faults below to rehearse a cloudy night.
            </p>
          </div>
          {error && <p className="text-xs text-status-error bg-status-error/10 rounded px-3 py-2">{error}</p>}

          <Section title="Status">
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
              <Stat label="State" value={st?.state ?? '…'}
                tone={h?.guiding ? 'text-emerald-300' : st?.active ? 'text-amber-300' : 'text-slate-300'} />
              <Stat label={h?.guiding ? 'Guiding for' : 'Unguided for'}
                value={h ? `${fmt(h.guiding ? h.guiding_for_s : h.unguided_for_s, 0)} s` : '—'} />
              <Stat label="RMS, last minute" value={`${fmt(w?.rms_total)}″`} />
              <Stat label="Losses / unguided (1 min)" value={w ? `${w.losses} / ${fmt(w.unguided_s, 0)} s` : '—'} />
            </div>
            {h && !h.guiding && h.reason && <p className="text-xs text-slate-500 mt-2">Reason: {h.reason.replace('_', ' ')}</p>}
          </Section>

          <Section title="Guiding">
            <div className="flex gap-2 flex-wrap">
              {st?.connected
                ? <Button size="sm" variant="outline" onClick={act(sim.disconnect)}>Disconnect</Button>
                : <Button size="sm" onClick={act(sim.connect)}>Connect</Button>}
              <Button size="sm" disabled={!st?.connected || st.active} onClick={act(() => sim.guide())}>Start guiding</Button>
              <Button size="sm" variant="outline" disabled={!st?.active} onClick={act(sim.stop)}>Stop</Button>
              <Button size="sm" variant="outline" disabled={!h?.guiding} onClick={act(() => sim.dither())}>Dither</Button>
            </div>
          </Section>

          <Section title="Faults">
            <div className="flex gap-2 flex-wrap">
              <Button size="sm" variant="outline" onClick={act(() => sim.loseStar(10))}>Lose star 10 s</Button>
              <Button size="sm" variant="outline" onClick={act(() => sim.loseStar(120))}>Lose star 2 min</Button>
              <Button size="sm" variant="outline" onClick={act(() => sim.loseStar(null))}>Lose star until cleared</Button>
              <Button size="sm" variant="outline" onClick={act(sim.stopGuidingFault)}>Guiding stops</Button>
              <Button size="sm" variant="outline" onClick={act(() => sim.failSettles(1))}>Fail next settle</Button>
              <Button size="sm" variant="outline" onClick={act(() => sim.failSettles(3))}>Fail next 3 settles</Button>
              <Button size="sm" variant="ghost" onClick={act(sim.clearFaults)}>Clear faults</Button>
            </div>
            {f && (f.star_lost || f.settle_failures_left > 0) && (
              <p className="text-xs text-amber-300 mt-2">
                {f.star_lost && (f.star_back_in_s == null ? 'Star lost until cleared. ' : `Star back in ${fmt(f.star_back_in_s, 0)} s. `)}
                {f.settle_failures_left > 0 && `${f.settle_failures_left} settle failure(s) pending.`}
              </p>
            )}
            <p className="text-xs text-slate-500 mt-2">
              "Lose star" keeps guiding trying (it recovers when the star is back); "Guiding stops"
              is PHD2 giving up — guiding must be started again.
            </p>
          </Section>

          {settings && (
            <Section title="Settings">
              {([
                ['rms_arcsec', 'Guiding RMS', '″'],
                ['step_interval_s', 'Guide exposure every', 's'],
                ['settle_extra_s', 'Extra settling time', 's'],
                ['pixel_scale', 'Pixel scale', '″/px'],
                ['time_scale', 'Time scale', '×'],
              ] as const).map(([key, label, unit]) => (
                <label key={key} className="flex items-center gap-3 py-1">
                  <span className="text-sm text-slate-300 w-48">{label}</span>
                  <div className="w-24">
                    <Input inputSize="sm" value={draft[key] ?? String(settings[key])}
                      onChange={(e) => setDraft({ ...draft, [key]: e.target.value })} />
                  </div>
                  <span className="text-xs text-slate-500">{unit}</span>
                </label>
              ))}
              {([
                ['lose_star_on_slew', 'A slew while guiding loses the star (guiding stops)'],
                ['connected_at_startup', 'Connected at startup'],
              ] as const).map(([key, label]) => (
                <div key={key} className="flex items-center gap-3 py-1">
                  <ToggleSwitch label={label} checked={settings[key]}
                    onChange={() => setSettings({ ...settings, [key]: !settings[key] })} />
                  <span className="text-sm text-slate-300">{label}</span>
                </div>
              ))}
              <div className="flex items-center gap-3 mt-2">
                <Button size="sm" onClick={saveSettings}>Save settings</Button>
                {message && <span className="text-xs text-slate-400">{message}</span>}
              </div>
            </Section>
          )}
        </div>
      </div>
      <EventLog filter={['guide_simulator', 'guiding']} />
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h2 className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-2">{title}</h2>
      {children}
    </section>
  )
}

function Stat({ label, value, tone = 'text-slate-200' }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded border border-surface-border bg-surface-raised px-3 py-2">
      <div className="text-[11px] text-slate-500">{label}</div>
      <div className={`font-mono ${tone}`}>{value}</div>
    </div>
  )
}
